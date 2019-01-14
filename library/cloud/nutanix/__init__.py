# -*- coding: utf-8 -*-
from ansible.module_utils.nutanix import *

class NutanixBase(object):

    def __init__(self, module):
        self.module = module
        self.client = NutanixClient(module)

    def get_vm_instance(self, vm_uuid):
        uri = '/vms/{0}'.format(vm_uuid)
        return self.client.open_url(uri=uri)

    def get_vm_uuid_from_task(self, task_uuid):
        uri = '/tasks/{0}'.format(task_uuid)
        tasks = self.client.open_url(uri=uri)
        vm_uuid = tasks.get('entity_list')[0].get('entity_id')

        return vm_uuid

    def get_storage_uuid(self, storage_name):
        uri = '/storage_containers/'
        storages = self.client.open_url(uri=uri)
        storage = list(filter(lambda x: x.get('name') == storage_name, storages.get('entities')))

        return storage[0].get('storage_container_uuid')