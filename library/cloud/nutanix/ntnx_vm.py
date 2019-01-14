# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.nutanix import *
from ansible.module_utils._text import to_bytes, to_native

from time import sleep

import traceback
import base64
import re

__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: ntnx_vm
short_description: create or cancel a virtual instance in Nutanix
description:
  - Creates or cancels Nutanix instances.
  - When created, optionally waits for it to be 'running'.
version_added: "1.0"
options:
  image:
    description:
      - Image Template to be used for new virtual instance.
  hostname:
    description:
      - Hostname to be provided to a virtual instance.
    required: true
  description:
    description:
      - description to be provided to a virtual instance.
  cores_per_vcpu:
    description:
      - Count of cores per vcpu to be assigned to new virtual instance.
    default: 1
  vcpu:
    description:
      - Count of cpu to be assigned to new virtual instance.
    default: 1
  memory:
    description:
      - Amount of memory to be assigned to new virtual instance.
      - Unit: Gigabyte
    default: 4
  vm_disks:
    description:
      - a list of hash/dictionaries of volumes to add to the new instance; '[{"key":"value", "key":"value"}]'; 
        keys allowed are 
      - storage_name (str; required), device_index (int, list index num), device_bus (deprecated), size (int, GB)
  vm_nics:
     description:
      - List of interface to be assigned to new virtual instance. 
  user_data:
    description:
      - opaque blob of data which is made available to the virtual instance
  state:
    description:
      - Create, or cancel a virtual instance.
      - Specify C(present) for create, C(absent) to cancel.
    choices: ['present', 'absent', 'started', 'restarted', 'stopped']
    default: present
requirements:
    - python >= 2.6
    - requests >= 2.9
author:
- Insun Kim (insun.kim@sk.com)
'''

EXAMPLES = '''
- name: Build instance
  hosts: localhost
  gather_facts: no
  tasks:
    - name: Build instance request
      ntnx_vm:
        images: feaed57d-d35e-488c-988e-a3df00d045f9
        hostname: instance-1
        cores_per_vcpu: 1
        vcpu: 2
        memory: 4
        state: present

- name: Build instance Add Disks
  hosts: localhost
  gather_facts: no
  tasks:
    - name: Build instance request
      ntnx_vm:
        images: feaed57d-d35e-488c-988e-a3df00d045f9
        hostname: instance-2
        cores_per_vcpu: 1
        vcpu: 2
        memory: 4
        vm_disks:
          - storage_name: SelfServiceContainer
            device_bus: SCSI
            size: 50
        state: present

- name: Terminate instance
  hosts: localhost
  gather_facts: no
  tasks:
    - name: Terminate instance request
      ntnx_vm:
        hostname: instance-2
        state: absent
'''


class NtnxVm:

    def __init__(self, module):
        self.module = module
        self._client = NutanixClient(module)

    def vm_user_data(self, hostname, vm_nics):
        ip_regex = re.compile(r'\d{1,3}.\d{1,3}.\d{1,3}')
        ethx = [dict(number=idx, ipaddr=eth.get('ip'), gateway='{0}.1'.format(ip_regex.match(eth.get('ip')).group()))
                for idx, eth in enumerate(vm_nics)]

        user_data = """
            #cloud-config 
            #

            write_files:
              {write_files}
            
            runcmd:
              - sh /var/lib/cloud/scripts/per-once/skp-cloud-init.sh
              - service network restart"""
        default_script = """
              - path: /tmp/vm_info
                content: |
                  HOSTNAME={0}"""
        network_script = """
              - path: /etc/sysconfig/network-scripts/ifcfg-eth{number}
                content: |
                  TYPE=Ethernet
                  DEVICE=eth{number}
                  USERCTL=no
                  BOOTPROTO=static
                  IPADDR={ipaddr}
                  GATEWAY={gateway}
                  NETMASK=255.255.255.0
                  ONBOOT=yes
                  IPV6INIT=no"""

        network_script = [network_script.format(**i) for i in ethx]
        user_data_params = dict(
            write_files=default_script.format(hostname) + ''.join(network_script)
        )
        # self.module.exit_json(msg=user_data_format.format(**user_data))
        return dict(userdata=user_data.format(**user_data_params))

    def get_vm_instance(self, uuid):
        return self._client.ntnx_open_url(uri='/vms/{0}'.format(uuid))

    def get_vm_uuid_from_task(self, uuid):
        uri = '/tasks/{0}'.format(uuid)
        vm_uuid = None

        for i in range(0, 10):
            try:
                tasks = self._client.ntnx_open_url(uri=uri)
                vm_uuid = tasks.get('entity_list')[0].get('entity_id')
                break

            except TypeError:
                sleep(0.5)
                pass

        if vm_uuid is None:
            raise Exception('vm_uuid is None')

        return vm_uuid

    def get_storage_uuid(self, storage_name):

        try:
            entities = self._client.ntnx_open_url(
                uri='/storage_containers/?search_string={0}'.format(storage_name)).get('entities')

            return entities[0].get('storage_container_uuid')

        except IndexError:
            raise Exception('{0} is not found.'.format(storage_name))

    def get_vlan_uuid(self, vlan_name):
        try:
            networks = self._client.ntnx_open_url(uri='/networks/')
            network = list(filter(lambda x: x.get('name') == vlan_name, networks.get('entities')))[0]

            return network.get('uuid')

        except IndexError:
            raise Exception('{0} is not found.'.format(vlan_name))

    def is_vm_instance(self, hostname):
        vm_filter = 'vm_name=={0}'.format(hostname)
        uri = '/vms/?filter={0}&include_vm_disk_config=true&include_vm_nic_config=true'.format(vm_filter)
        entities = self._client.ntnx_open_url(uri=uri).get('entities')
        if len(entities) == 1:
            return True, entities[0]

        elif len(entities) == 0:
            return False, None

        else:
            raise Exception('It does not exist or there are many instances of the same name.: {0}'.format(hostname))

    def vm_power_state(self, uuid, state):
        uri = '/vms/{0}/set_power_state'.format(uuid)
        transition = ()

        if state in ('stopped', 'restarted'):
            transition += ('OFF',)

        if state in ('present', 'started', 'restarted'):
            transition += ('ON',)

        for i in transition:
            self._client.ntnx_open_url(method='post', uri=uri, data=dict(transition=i))

    def detach_nic(self, uuid, vm_nics):
        pass

    def attach_nic(self, uuid, current_nic, vm_nics):
        pass

    def detach_disk(self, uuid, vm_disks):
        pass

    def attach_disk(self, uuid, current_disk, vm_disks):
        changed = False
        vm_disk_specs = [dict(
            is_cdrom=False,
            disk_address={
                'device_bus': 'SCSI',
                'device_index': i,
            },
            vm_disk_create={
                'storage_container_uuid': self.get_storage_uuid(disk.get('storage_name')),
                'size': (1024 ** 3) * disk.get('size')
            }
        ) for i, disk in enumerate(vm_disks, start=1)]

        if len(current_disk) > 0:
            current_disk_len = len([i for i in current_disk if i.get('disk_address').get('device_bus') == 'scsi']) - 1
            del vm_disk_specs[0:current_disk_len]

        if vm_disk_specs:
            uri = '/vms/{0}/disks/attach'.format(uuid)
            payload = dict(vm_disks=vm_disk_specs)
            self._client.ntnx_open_url(method='post', uri=uri, data=payload)
            changed = True

        return changed

    def get_vm_nics_spec(self, vm_nics):
        vm_nics_spec = [dict(network_uuid=self.get_vlan_uuid(vlan_name=i.get('vlan_name'))) for i in vm_nics]

        return vm_nics_spec

    def delete_vm_instance(self, module):
        # Feature to be applied in the future
        #
        changed = False
        hostname = module.params.get('hostname')
        is_instance, instance = self.is_vm_instance(hostname)
        try:
            if is_instance:
                uri = '/vms/{0}'.format(instance.get('uuid'))
                self._client.ntnx_open_url(method='delete', uri=uri, data=dict(delete_snapshots=True))
                changed = True

            else:
                module.fail_json(msg='There are instances that do not exist or are duplicates.: {0}'.format(hostname),
                                 exception=traceback.format_exc())

            return changed, None

        except Exception as e:
            module.fail_json(msg=e, exception=traceback.format_exc())

    def create_vm_instance(self, module):
        image_uuid = module.params.get('image_uuid')
        hostname = module.params.get('hostname')
        cores = module.params.get('cores_per_vcpu')
        vcpu = module.params.get('num_vcpu')
        memory_mb = 1024 * module.params.get('memory_size')
        vm_disks = module.params.get('vm_disks')
        vm_nics = module.params.get('vm_nics')
        state = module.params.get('state')
        current_disk = []

        try:
            changed = False
            is_instance, instance = self.is_vm_instance(hostname)
            vm_spec = dict(
                name=hostname,
                num_cores_per_vcpu=cores,
                num_vcpus=vcpu,
                memory_mb=memory_mb
            )

            if is_instance:
                # Feature to be applied in the future
                # In case of existing vm, it is possible to scale up / down according to specification change.
                # Currently, only cpu and memory can be modified.

                vm_uuid = instance.get('uuid')
                # current_disk = instance.get('vm_disk_info')

                for k, v in instance.items():
                    if v == vm_spec.get(k, None):
                        del vm_spec[k]

                if vm_spec:
                    self.vm_power_state(uuid=vm_uuid, state='stopped')
                    uri = '/vms/{0}'.format(vm_uuid)
                    self._client.ntnx_open_url(method='put', uri=uri, data=vm_spec)

                    changed = True

            else:
                vm_spec.update(dict(
                    vm_nics=self.get_vm_nics_spec(vm_nics),
                    override_network_config=True,
                    clone_affinity=False
                ))
                uri = '/vms/{0}/clone'.format(image_uuid)
                # user_data = module.params.get('user_data')
                user_data = self.vm_user_data(hostname=hostname, vm_nics=vm_nics)
                payload = dict(spec_list=[vm_spec], vm_customization_config=user_data)
                tasks = self._client.ntnx_open_url(method='post', uri=uri, data=payload)
                vm_uuid = self.get_vm_uuid_from_task(tasks.get('task_uuid'))

                changed = True

                if vm_disks:
                    changed = self.attach_disk(uuid=vm_uuid, current_disk=current_disk, vm_disks=vm_disks)

            self.vm_power_state(uuid=vm_uuid, state=state)

            return changed, self.get_vm_instance(vm_uuid)

        except Exception as e:
            module.fail_json(msg=e, exception=traceback.format_exc())


def main():
    argument_spec = ntnx_common_argument_spec()
    argument_spec.update(
        dict(
            image_uuid={'required': True, 'aliases': ['image'], 'default': None},
            hostname={'required': True},
            description={'required': False},
            cores_per_vcpu={'type': 'int', 'aliases': ['num_cores_per_vcpu'], 'default': 1},
            num_vcpu={'type': 'int', 'aliases': ['vcpu'], 'default': 2},
            memory_size={'type': 'int', 'aliases': ['memory'], 'default': 4},
            vlan_name={'aliases': ['vlan'], 'default': None},
            vm_disks={'type': 'list'},
            vm_nics={'required': True, 'type': 'list'},
            user_data={},
            state={'choices': ['present', 'absent', 'started', 'stopped', 'restarted'], 'default': 'present'},
            count={'type': 'int', 'default': 1}
        )
    )

    module = AnsibleModule(argument_spec=argument_spec)

    ntnx_vm = NtnxVm(module)

    if module.params.get('state') == 'absent':
        changed, instance = ntnx_vm.delete_vm_instance(module)

    else:
        changed, instance = ntnx_vm.create_vm_instance(module)

    module.exit_json(changed=changed, instance=instance)


if __name__ == '__main__':
    main()
