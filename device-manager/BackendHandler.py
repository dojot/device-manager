"""
    Defines common handler interface and implementations for devices
"""

import json
import logging
import traceback
import requests

LOGGER = logging.getLogger('device-manager.' + __name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)

# TODO: this actually is a symptom of bad responsability management.
# All device bookkeeping should be performed on a single (perhaps this) service, with the
# services that implement specific features referring back to the single device management
# service for their transient data.

class BackendHandler(object):
    """
        Abstract class that represents an implementation backend on the internal middleware
        infrastructure.
    """

    def create(self, device):
        """
            Creates the given device on the implemented backend.
            :param device: Dictionary with the full device configuration
            :returns: True if operation succeeded, false otherwise
        """
        raise NotImplementedError('Abstract method called')

    def remove(self, device_id):
        """
            Removes the device identified by the given id
            :param device_id: unique identifier of the device to be removed
            :returns: True if operation succeeded, false otherwise
        """
        raise NotImplementedError('Abstract method called')

    def update(self, device):
        """
            Updates the given device on the implemented backend.
            :param device: Dictionary with the full device configuration. Must contain an 'id'
                           field with the unique identifier of the device to be updated. That
                           field must not be changed.
            :returns: True if operation succeeded, false otherwise
        """
        raise NotImplementedError('Abstract method called')



class IotaHandler(BackendHandler):
    """ Abstracts interaction with iotagent-json for MQTT device management """
    # TODO: this should be configurable (via file or environment variable)
    def __init__(self, baseUrl='http://iotagent:4041/iot',
                       orionUrl='http://orion:1026/v1/contextEntities',
                       service='devm'):
        self.baseUrl = baseUrl
        self.orionUrl = orionUrl
        self.service = service
        self._headers = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'Content-Type':'application/json',
            'cache-control': 'no-cache'
        }
        self._noBodyHeaders = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'cache-control': 'no-cache'
        }

    def __get_topic(self, device):
        topic = ''
        if 'topic' in device:
            topic = device.topic
        else:
            topic = "/%s/%s/attrs" % (self.service, device['id'])

        return topic

    def __get_config(self, device):

        freq = 2000
        if 'freq' in device.keys():
            freq = device['freq']

        # Currently, there's no efficient way (apart from setting extra metadata) to have the
        # context broker store a human-readable label to be associated with an entity (device).
        # Here we use entity_type as a cheap alternative
        return {
            # this is actually consumed by iotagent
            'device_id': device['id'],
            # becomes entity type for context broker
            'entity_type': 'device',
            # becomes entity id for context broker
            'entity_name': device['id'],
            'attributes': device['attrs'],
            # this is actually consumed by iotagent
            'internal_attributes': {
                "attributes" : [
                    {"topic": "tcp:mqtt:%s" % self.__get_topic(device)},
                ],
                "timeout": {
                    "periodicity": freq,
                    "waitMultiplier": 3
                }
            },
            # becomes part of the attribute list on context broker
            'static_attributes': [
                # TODO this should be part of the entity metadata
                {'name': 'user_label', 'type':'string', 'value': device['label']}
            ]
        }

    def create(self, device):
        """ Returns boolean indicating device creation success. """

        try:
            svc = json.dumps({
                "services": [{
                    "resource": "devm",
                    "apikey": self.service,
                    "entity_type": 'device'
                }]
            })
            response = requests.post(self.baseUrl + '/services', headers=self._headers, data=svc)
            if not (response.status_code == 409 or
                    (response.status_code >= 200 and response.status_code < 300)):
                return False
        except requests.ConnectionError:
            return False

        try:
            response = requests.post(self.baseUrl + '/devices', headers=self._headers,
                                     data=json.dumps({'devices':[self.__get_config(device)]}))
            return response.status_code >= 200 and response.status_code < 300
        except requests.ConnectionError:
            return False

    def remove(self, deviceid):
        """ Returns boolean indicating device removal success. """

        try:
            response = requests.delete(self.baseUrl + '/devices/' + deviceid, headers=self._noBodyHeaders)
            if response.status_code >= 200 and response.status_code < 300:
                response = requests.delete('%s/%s' % (self.orionUrl, deviceid), headers=self._noBodyHeaders)
                if response.status_code >= 200 and response.status_code < 300:
                    return True
        except requests.ConnectionError:
            return False

    def update(self, device):
        """ Returns boolean indicating device update success. """

        self.remove(device['id'])
        return self.create(device)

class OrionHandler(BackendHandler):
    """ Abstracts interaction with iotagent-json for MQTT device management """
    # TODO: this should be configurable (via file or environment variable)
    def __init__(self, baseUrl='http://iotagent:4041/iot', service='devm', device_type='virtual'):
        self.baseUrl = baseUrl
        self.service = service
        self.device_type = device_type
        self._headers = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'Content-Type':'application/json',
            'cache-control': 'no-cache'
        }
        self._noBodyHeaders = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'cache-control': 'no-cache'
        }

    @staticmethod
    def get_config(device):

        # Currently, there's no efficient way (apart from setting extra metadata) to have the
        # context broker store a human-readable label to be associated with an entity (device).
        # Here we use entity_type as a cheap alternative
        return {
            # this is actually consumed by iotagent
            'device_id': device['id'],
            # becomes entity type for context broker
            'entity_type': 'device',
            # becomes entity id for context broker
            'entity_name': device['id'],
            'attributes': device['attrs'],

            # becomes part of the attribute list on context broker
            'static_attributes': [
                # TODO this should be part of the entity metadata
                {'name': 'user_label', 'type':'string', 'value': device['label']}
            ]
        }

    def create(self, device):
        """ Returns boolean indicating device creation success. """

        try:
            svc = json.dumps({
                "services": [{
                    "resource": "devm",
                    "apikey": self.service,
                    "entity_type": 'device'
                }]
            })
            response = requests.post(self.baseUrl + '/services', headers=self._headers, data=svc)
            if not (response.status_code == 409 or
                    (response.status_code >= 200 and response.status_code < 300)):
                return False
        except requests.ConnectionError:
            return False

        try:
            response = requests.post(self.baseUrl + '/devices', headers=self._headers,
                                     data=json.dumps({'devices':[OrionHandler.get_config(device)]}))
            return response.status_code >= 200 and response.status_code < 300
        except requests.ConnectionError:
            return False

    def remove(self, deviceid):
        """ Returns boolean indicating device removal success. """

        try:
            response = requests.delete(self.baseUrl + '/devices/' + deviceid, headers=self._noBodyHeaders)
            return response.status_code >= 200 and response.status_code < 300
        except requests.ConnectionError:
            return False

    def update(self, device):
        """ Returns boolean indicating device update success. """

        config = OrionHandler.get_config(device)
        config.pop('internal_attributes', None) # TODO add support for topic edition on iotagent
        try:
            response = requests.put(self.baseUrl + '/devices/' + device['id'],
                                    headers=self._headers, data=json.dumps(config))
            return response.status_code >= 200 and response.status_code < 300
        except requests.ConnectionError:
            return False

# Temporarily create a subscription to persist device data
# TODO this must be revisited in favor of a orchestrator-based solution
class PersistenceHandler(object):
    """
        Abstracts the configuration of subscriptions targeting the default
        history backend (STH)
    """
    # TODO: this should be configurable (via file or environment variable)
    def __init__(self, service='devm',
                 baseUrl='http://orion:1026/v1/contextSubscriptions',
                 targetUrl="http://sth:8666/notify"):
        self.baseUrl = baseUrl
        self.targetUrl = targetUrl
        self.service = service
        self._headers = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'Content-Type':'application/json',
            'cache-control': 'no-cache'
        }
        self._noBodyHeaders = {
            'Fiware-service': service,
            'Fiware-servicePath': '/',
            'cache-control': 'no-cache'
        }

    def create(self, device_id, device_type='device'):
        """ Returns subscription id on success. """

        try:
            svc = json.dumps({
                "entities": [{
                    "type": device_type,
                    "isPattern": "false",
                    "id": device_id
                }],
                "reference" : self.targetUrl,
                "duration": "P10Y",
                "notifyConditions": [{"type": "ONCHANGE"}]
            })
            response = requests.post(self.baseUrl, headers=self._headers, data=svc)
            if not (response.status_code == 409 or
                    (response.status_code >= 200 and response.status_code < 300)):
                return None

            # return the newly created subs
            reply = response.json()
            return reply['subscribeResponse']['subscriptionId']

        except (requests.ConnectionError, ValueError):
            LOGGER.error('Failed to create subscription')
            return None

    def remove(self, subsId):
        """ Returns boolean indicating subscription removal success. """

        try:
            response = requests.delete(self.baseUrl + '/' + subsId, headers=self._noBodyHeaders)
            return response.status_code >= 200 and response.status_code < 300
        except requests.ConnectionError:
            return False

def annotate_status(device_list, orion="http://orion:1026", service='devm'):
    """ Returns the given device list with updated device status as seen on the ctx broker"""

    url = "%s/NGSI10/queryContext" % orion
    query = json.dumps({"entities": [{"isPattern": "true", "id": ".*"}]})
    headers = {
        'Content-Type': 'application/json',
        'Fiware-service': service,
        'Fiware-servicepath': '/'
    }

    try:
        response = requests.post(url, headers=headers, data=query)
    except requests.ConnectionError:
        LOGGER.error("Failed to retrieve status data from context broker: connection failed")
        return []

    if response.status_code < 200 and response.status_code >= 300:
        LOGGER.error("Failed to retrieve status data from context broker: %d" % response.status_code)
        return []


    reply = response.json()
    if 'errorCode' in reply:
        LOGGER.error(
            "Failed to retrieve status data from context broker: %s" % reply['errorCode']['reasonPhrase'])
        return []

    status_map = {}
    try:
        for ctx in reply['contextResponses']:
            for attr in ctx['contextElement']['attributes']:
                if attr['name'] == 'device-status':
                    status_map[ctx['contextElement']['id']] = attr['value']

        for dev in device_list:
            if dev['id'] in status_map.keys():
                dev['status'] = status_map[dev['id']]

        LOGGER.debug('will return ' + json.dumps(device_list))
        return device_list
    except KeyError as exception:
        LOGGER.error(exception)
        return []
