# -*- coding: utf-8 -*-

from requests import post
try:
    import json
except ImportError:
    import simplejson as json


class TransmissionRPC(dict):
    """ Wrap the Transmission JSON API """
    def __init__(self, host='localhost', port=9091, username='',
                 password=''):
        self.url = f'http://{host}:{port}/transmission/rpc'
        self.username = username
        self.password = password
        self.sid = None

    def __call__(self, **kwargs):
        method = '.'.join(map(str, self.n))
        self.n = []
        return TransmissionRPC.__dict__['request'](self, method, kwargs)

    def __getattr__(self, name):
        if 'n' not in self.__dict__:
            self.n = []
        self.n.append(name)
        return self

    def request(self, method, kwargs):
        # Create JSON request
        data = {'method': method.replace('_', '-'), 'arguments': kwargs}
        data = json.JSONEncoder().encode(data)
        # Send data to transmission
        response = post(self.url, data=data, auth=(self.username,
                        self.password),
                        headers={'X-Transmission-Session-Id': self.sid})
        if response.status_code == 409:
            self.sid = response.headers['X-Transmission-Session-Id']
            return self.request(method, kwargs)
        response.raise_for_status()
        # Decode and return the response
        rv = response.json()
        if 'success' != rv['result']:
            raise ValueError(rv['result'])
        return rv['arguments']
