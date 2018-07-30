import json
import threading
from kafka import KafkaConsumer, KafkaProducer
from kafka import ConsumerRebalanceListener
from kafka.errors import KafkaTimeoutError
from flask import g
import redis
import uuid

from .conf import CONFIG
from .KafkaNotifier import get_topic
from .DatabaseModels import Device
from .DatabaseHandler import db
from .app import app

from DeviceManager.Logger import Log
from datetime import datetime
import time


timeStamp = datetime.fromtimestamp(time.time()).strftime('%d/%m/%Y:%H:%M:%S')
LOGGER = Log().color_log()

class Listener(ConsumerRebalanceListener):
    def __init__(self, monitor):
        self.__monitor = monitor
        self.__collectors = {}

    def on_partitions_assigned(self, assigned):
        LOGGER.debug(f'[{timeStamp}] |{__name__}| got listener event {len(assigned)} {assigned}')
        for partition in assigned:
            self.__monitor.collect(partition.partition)
            if partition not in self.__collectors.keys():
                LOGGER.debug(f"[{timeStamp}] |{__name__}| will start iterator")
                self.__monitor.begin(partition.partition)

class StatusMonitor:
    def __init__(self, tenant):
        self.producer = KafkaProducer(value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                                      bootstrap_servers=CONFIG.get_kafka_url())

        self.tenant = tenant
        self.topic=get_topic(self.tenant, CONFIG.device_subject)

        self.redis = redis.StrictRedis(host=CONFIG.redis_host, port=CONFIG.redis_port)

        self.__consumer_thread = threading.Thread(target=self.run)
        self.__consumer_thread.daemon = True
        self.__consumer_thread.start()

    @staticmethod
    def wait_init(consumer):
        done = False
        while not done:
            try:
                # make sure we process initial partition assignment messages
                consumer.poll()
                consumer.seek_to_end()
                done = True
            except AssertionError as error:
                # give kafka some time to assign us a partition
                time.sleep(1)

    def run(self):
        group_id="device-manager.monitor#" + str(uuid.uuid4())         
        start = time.time()
        LOGGER.debug(F'[{timeStamp}] |{__name__}| will create consumer {CONFIG.get_kafka_url()} {group_id} {self.topic}')
        consumer = KafkaConsumer(bootstrap_servers=CONFIG.get_kafka_url(), group_id=group_id)
        consumer.subscribe(topics=[self.topic], listener=Listener(self))
        StatusMonitor.wait_init(consumer)
        LOGGER.debug(f'[{timeStamp}] |{__name__}| kafka consumer created {self.topic} - {time.time() - start}')
        LOGGER.debug(consumer.assignment())
        for message in consumer:
            LOGGER.debug(f"[{timeStamp}] |{__name__}| Got kafka event [{self.topic}] {message}")
            data = None
            try:
                data = json.loads(message.value)
            except Exception as error:
                LOGGER.error(f"[{timeStamp}] |{__name__}| Received message is not valid json {error}")
                continue

            metadata = data.get('metadata', None)
            if metadata is None:
                LOGGER.error(f'[{timeStamp}] |{__name__}| Invalid kafka event detected - no metadata included')
                continue

            reason = metadata.get('reason', None)
            if reason == 'statusUpdate':
                continue

            deviceid = metadata.get('deviceid', None)
            tenant = metadata.get('tenant', None)
            if (deviceid is None) or (tenant is None):
                LOGGER.warning(f"[{timeStamp}] |{__name__}| Missing device identification from event")
                continue

            self.set_online(tenant, deviceid, message.partition, metadata.get('exp', None))

    @staticmethod
    def get_key_for(tenant, device, partition):
        return 'st:{}:{}:{}:exp'.format(tenant, device, partition)

    @staticmethod
    def parse_key_from(key):
        parsed = key.split(':')
        return {
            'tenant': parsed[1],
            'device': parsed[2],
            'partiion': parsed[3]
        }

    def notify(self, tenant, device, status):
        message = {
            'metadata': {
                'deviceid': device,
                'tenant': tenant,
                'status': status,
                'reason': 'statusUpdate'
            }
        }
        self.producer.send(self.topic, message)

    @staticmethod
    def default_exp(tenant, device):
        with app.app_context():
            g.tenant = tenant
            db.session.execute("SET search_path TO %s" % tenant)
            device = db.session.query(Device).filter(Device.id == device).one()
            for template in device.templates:
                for attr in template.config_attrs:
                    if (attr.type == "meta") and (attr.label == "device_timeout"):
                        return int(attr.static_value)/1000.0
            return CONFIG.status_timeout


    def set_online(self, tenant, device, partition, exp):
        """
        Brands given device as online for the stipulated period of time 'exp'
        """
        if exp is None:
            exp = StatusMonitor.default_exp(tenant, device)

        LOGGER.info(f'[{timeStamp}] |{__name__}| will set {tenant}:{device} online for {exp}s')

        key = StatusMonitor.get_key_for(tenant, device, partition)
        old_ts = self.redis.get(key)
        if old_ts is None:
            # publish online event
            self.notify(tenant, device, 'online')

        self.redis.set(key, time.time() + exp)

    def begin(self, partition):
        gc_thread = threading.Thread(target=self.iterate, args=(partition, -1))
        gc_thread.daemon = True
        gc_thread.start()

    def iterate(self, partition=None, times=-1):
        """
        Periodically invoke iterator
        """
        LOGGER.debug(f"[{timeStamp}] |{__name__}| starting iterator")
        while times != 0:
            # now = time.time()
            # print('[times] gc is about to run {}'.format(now - self.lastgc))
            # self.lastgc = now
            self.collect(partition)
            time.sleep(2)
            # LOGGER.debug('[{}] |{}| [times] gc is about to run {}'.format(timeStamp, __name__, now - self.lastgc))
            if times > 0:
                times -= 1

    def collect(self, partition):
        match = StatusMonitor.get_key_for(self.tenant, '*', partition)
        devices = []

        cursor, data = self.redis.scan(0, match, count=1000)
        for i in data:
            if i is not None:
                devices.append(i.decode('utf-8'))
                LOGGER.debug(f'[{timeStamp}] |{__name__}| scan {match} {cursor} {data}')
        while cursor != 0:
            cursor, data = self.redis.scan(cursor, match, count=1000)
            for i in data:
                if i is not None:
                    devices.append(i.decode('utf-8'))
                    LOGGER.debug(f'[{timeStamp}] |{__name__}| scan {cursor} {data}')

        now = time.time()
        for device in devices:
            try:
                LOGGER.debug(f'[{timeStamp}] |{__name__}| gc devices {devices}')
                exp = float(self.redis.get(device).decode('utf-8'))
                LOGGER.debug(f'[{timeStamp}] |{__name__}| will check {device} {exp}')
                if now > exp:
                    self.redis.delete(device)
                    LOGGER.debug(f'[{timeStamp}] |{__name__}| device {device} offline')
                    parsed = device.split(':')
                    self.notify(parsed[1],parsed[2],'offline')
            except Exception as error:
                LOGGER.error(f'[{timeStamp}] |{__name__}| Failed to process device "{device}": {error}')

    @staticmethod
    def get_status(tenant, device=None):
        """
        Returns boolean indicating whether device is online or not.
        """
        client = redis.StrictRedis(host=CONFIG.redis_host, port=CONFIG.redis_port)
        match = StatusMonitor.get_key_for(tenant, device if device is not None else '*', '*')
        status = {}
        timeref = time.time()

        def iterate(data):
            for key in data:
                if key is not None:
                    device = StatusMonitor.parse_key_from(key.decode('utf-8'))['device']
                    try:
                        exp = float(client.get(key).decode('utf-8'))
                    except AttributeError:
                        exp = None
                    if (exp is not None) and (timeref < exp):
                        status[device] = 'online'
                    else:
                        status[device] = 'offline'

        cursor, data = client.scan(0, match, count=1000)
        iterate(data)
        while cursor != 0:
            cursor, data = client.scan(cursor, match, count=1000)
            iterate(data)

        return status


