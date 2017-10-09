"""
    Defines common handler interface and implementations for devices
"""

import json
import logging
import traceback
import requests

from utils import HTTPRequestError

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
            :returns: True if operation succeeded
            :raises HTTPRequestError
        """
        raise NotImplementedError('Abstract method called')

    def remove(self, device_id):
        """
            Removes the device identified by the given id
            :param device_id: unique identifier of the device to be removed
            :raises HTTPRequestError
        """
        raise NotImplementedError('Abstract method called')

    def update(self, device):
        """
            Updates the given device on the implemented backend.
            :param device: Dictionary with the full device configuration. Must contain an 'id'
                           field with the unique identifier of the device to be updated. That
                           field must not be changed.
            :raises HTTPRequestError
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
        if device.topic:
            topic = device.topic
        else:
            topic = "/%s/%s/attrs" % (self.service, device.device_id)

        return topic

    def __get_config(self, device):

        base_config = {
            # this is actually consumed by iotagent
            'device_id': device.device_id,
            # becomes entity type for context broker
            'entity_type': 'device',
            # becomes entity id for context broker
            'entity_name': device.device_id,
            'attributes': [],
            # this is actually consumed by iotagent
            'internal_attributes': {
                "attributes" : [],
                "timeout": {"periodicity": device.frequency, "waitMultiplier": 3}
            },
            'static_attributes': []
        }

        for attr in device.template.attrs:
            if attr.type == 'dynamic':
                base_config['attributes'].append({
                    'name': attr.label,
                    'type': attr.value_type
                })
            elif attr.type == 'static':
                base_config['static_attributes'].append({
                    'name': attr.label,
                    'type': attr.value_type,
                    'value': attr.static_value
                })
            elif (attr.type == 'meta') and (attr.label == 'mqtt_topic'):
                # @BUG however nice, this doesn't seem to work with iotagent-json
                base_config['internal_attributes']['attributes'].append({
                    {"topic": "tcp:mqtt:%s" % attr.static_value},
                })
        return base_config


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
                error = "Failed to configure ingestion subsystem: service creation failed"
                raise HTTPRequestError(500, error)
        except requests.ConnectionError:
            raise HTTPRequestError(500, "Cannot reach ingestion subsystem (service)")

        try:
            response = requests.post(self.baseUrl + '/devices', headers=self._headers,
                                     data=json.dumps({'devices':[self.__get_config(device)]}))
            if not (response.status_code >= 200 and response.status_code < 300):
                error = "Failed to configure ingestion subsystem: device creation failed"
                raise HTTPRequestError(500, error)
        except requests.ConnectionError:
            raise HTTPRequestError(500, "Cannot reach ingestion subsystem (device)")

    def remove(self, deviceid):
        """ Returns boolean indicating device removal success. """

        try:
            response = requests.delete(self.baseUrl + '/devices/' + deviceid,
                                       headers=self._noBodyHeaders)
            if response.status_code >= 200 and response.status_code < 300:
                response = requests.delete('%s/%s' % (self.orionUrl, deviceid),
                                           headers=self._noBodyHeaders)
                if not (response.status_code >= 200 and response.status_code < 300):
                    error = "Failed to configure ingestion subsystem: device removal failed"
                    raise HTTPRequestError(500, error)
        except requests.ConnectionError:
            raise HTTPRequestError(500, "Cannot reach ingestion subsystem")

    def update(self, device):
        """ Returns boolean indicating device update success. """

        self.remove(device.device_id)
        return self.create(device)

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
                raise HTTPRequestError(500, "Failed to create subscription")

            # return the newly created subs
            reply = response.json()
            return reply['subscribeResponse']['subscriptionId']
        except ValueError:
            LOGGER.error('Failed to create subscription')
            raise HTTPRequestError(500, "Failed to create subscription")
        except requests.ConnectionError:
            raise HTTPRequestError(500, "Broker is not reachable")

    def remove(self, subsId):
        """ Returns boolean indicating subscription removal success. """

        try:
            response = requests.delete(self.baseUrl + '/' + subsId, headers=self._noBodyHeaders)
            if not (response.status_code >= 200 and response.status_code < 300):
                raise HTTPRequestError(500, "Failed to remove subscription")
        except requests.ConnectionError:
            raise HTTPRequestError(500, "Broker is not reachable")

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
