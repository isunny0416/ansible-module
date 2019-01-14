# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type

from ansible.module_utils.six import with_metaclass
from configparser import NoSectionError, NoOptionError
from ansible.module_utils.urls import open_url
from ansible.module_utils.six.moves.urllib.error import HTTPError

import configparser
import os
import json
import traceback


class Singleton(type):
    _instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instance


class Configuration:

    def __init__(self):
        try:
            config = configparser.ConfigParser(allow_no_value=True)
            config.read(os.path.join(os.getenv('HOME'), '.nutanix'))
            section = os.getenv('NUTANIX_HOST') if os.getenv('NUTANIX_HOST') else 'defaults'
            self._default_url = config.get(section, 'default_url', fallback=None)
            self._user_name = config.get(section, 'user_name', fallback=None)
            self._user_password = config.get(section, 'user_password', fallback=None)

        except NoSectionError:
            pass

        except NoOptionError:
            pass

    @property
    def default_url(self):
        return self._default_url

    @property
    def user_name(self):
        return self._user_name

    @property
    def user_password(self):
        return self._user_password


class NutanixClient(with_metaclass(Singleton, object)):

    def __init__(self, module):
        super(NutanixClient, self).__init__()
        self._module = module
        self._default_url = self._module.params.get('default_url')
        self._user_name = self._module.params.get('user_name')
        self._user_password = self._module.params.get('user_password')
        is_validate = self.validate_params(default_url=self._default_url,
                                           user_name=self._user_name,
                                           user_password=self._user_password)
        if not is_validate:
            module.fail_json(msg='undefined user config parameter')

    '''
    def raise_for_task_result(self, task_uuid):
        uri = '/tasks/{0}'.format(task_uuid)
        url = '{0}{1}'.format(self.default_url, uri)
        r = self._session.get(url)
        #r.raise_for_status()
        task = r.json()
        if task.get('meta_response', None) is not None:
            if task.get('meta_response').get('error_code') > 0:
                raise RequestException(task.get('meta_response').get('error_detail'))
    '''

    def ntnx_open_url(self, method='get', uri=None, data={}):
        try:
            r = open_url(url=self._default_url + uri, method=method, headers={'Content-Type': 'application/json'},
                         url_username=self._user_name, url_password=self._user_password, force_basic_auth=True,
                         data=json.dumps(data))

            return json.loads(r.read())

        except HTTPError as e:
            self._module.fail_json(msg=e, exception=traceback.format_exc())

    def validate_params(self, default_url=None, user_name=None, user_password=None):
        config = Configuration()
        is_validate = True

        if default_url is None:
            if os.environ.get('NUTANIX_DEFAULT_URL'):
                self._default_url = os.environ.get('NUTANIX_DEFAULT_URL')

            elif config.default_url:
                self._default_url = config.default_url

            else:
                is_validate = False

        if user_name is None:
            if os.environ.get('NUTANIX_USER_NAME'):
                self._user_name = os.environ.get('NUTANIX_USER_NAME')

            elif config.user_name:
                self._user_name = config.user_name

            else:
                is_validate = False

        if user_password is None:
            if os.environ.get('NUTANIX_USER_PASSWORD'):
                self._user_password = os.environ.get('NUTANIX_USER_PASSWORD')

            elif config.user_password:
                self._user_password = config.user_password

            else:
                is_validate = False

        return is_validate


def ntnx_common_argument_spec():
    return dict(
        default_url={'no_log': True, 'default': None},
        user_name={'aliases': ['id', 'user'], 'no_log': True, 'default': None},
        user_password={'aliases': ['password', 'pwd'], 'no_log': True, 'default': None},
    )
