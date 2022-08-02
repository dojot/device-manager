"""
    Defines common handler interface and implementations for devices
"""

import json
import traceback
import requests
from DeviceManager.utils import HTTPRequestError
from DeviceManager.KafkaNotifier import KafkaNotifier, DeviceEvent
from DeviceManager.conf import CONFIG
import logging
from datetime import datetime
import time
from DeviceManager.Logger import Log

 
LOGGER = Log().color_log()


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


class KafkaHandler:

    def __init__(self):
        self.kafkaNotifier = KafkaNotifier()

    def create(self, device, meta):
        """
            Publishes event to kafka broker, notifying device creation
        """

        LOGGER.info(f" Publishing create event to Kafka")
        self.kafkaNotifier.send_notification(DeviceEvent.CREATE, device, meta)

    def remove(self, device, meta):
        """
            Publishes event to kafka broker, notifying device removal
        """
        
        LOGGER.info(f" Publishing remove event to Kafka")
        self.kafkaNotifier.send_notification(DeviceEvent.REMOVE, device, meta)

    def update(self, device, meta):
        """
            Publishes event to kafka broker, notifying device update
        """

        LOGGER.info(f" Publishing create update to Kafka")
        self.kafkaNotifier.send_notification(DeviceEvent.UPDATE, device, meta)

    def configure(self, device, meta):
        """
            Publishes event to kafka broker, notifying device configuration
        """
        LOGGER.info(f" Publishing configure event to Kafka")
        self.kafkaNotifier.send_notification(DeviceEvent.CONFIGURE, device, meta, CONFIG.device_actuation_subject)

class KafkaInstanceHandler:
    
    kafkaNotifier = None

    def __init__(self):
        pass

    def getInstance(self, kafka_instance):
        """
        Instantiates a connection with Kafka, was created because 
        previously the connection was being created in KafkaNotifier
        once time every import.
        
        :param kafka_instance: An instance of KafkaHandler.
        :return An instance of KafkaHandler used to notify
        """
        
        if kafka_instance is None:
            self.kafkaNotifier = KafkaHandler()

        return self.kafkaNotifier
