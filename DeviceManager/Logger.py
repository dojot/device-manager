import logging
from logging import config as config_log
from colorlog import ColoredFormatter

from DeviceManager.conf import CONFIG
from DeviceManager.utils import HTTPRequestError

class Log:

    def __init__(self, LOG_LEVEL = CONFIG.log_level, 
        LOG_FORMAT = "[%(log_color)s%(asctime)-8s%(reset)s] |%(log_color)s%(module)-8s%(reset)s| %(log_color)s%(levelname)s%(reset)s: %(log_color)s%(message)s%(reset)s", DISABLED = False):

        #Disable all others modules logs
        LOGGING = {
            'version': 1,
            'disable_existing_loggers': True,
        }
        
        dateFormat = '%d/%m/%y - %H:%M:%S'
        config_log.dictConfig(LOGGING)
        self.formatter = ColoredFormatter(LOG_FORMAT, dateFormat)
        self.log = logging.getLogger('device-manager.' + __name__)
        self.log.setLevel(LOG_LEVEL)
        self.log.disabled = DISABLED
        self.level = LOG_LEVEL

        if not getattr(self.log, 'handler_set', None):
            self.stream = logging.StreamHandler()
            self.stream.setLevel(LOG_LEVEL)
            self.stream.setFormatter(self.formatter)
            self.log.setLevel(LOG_LEVEL)
            self.log.addHandler(self.stream)
            self.log.handler_set = True

    def update_log_level(self, LEVEL):
        levelToName = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET']

        try:
            self.log = logging.getLogger('device-manager.' + __name__)
            for hdlr in self.log.handlers[:]:
                self.log.removeHandler(hdlr)

            self.stream = logging.StreamHandler()
            self.stream.setLevel(LEVEL)
            self.stream.setFormatter(self.formatter)

            self.log.setLevel(LEVEL)
            self.log.addHandler(self.stream)
            self.log.handler_set = True

            self.level = LEVEL

        except ValueError:
            raise HTTPRequestError(400, "Unknown level: {} valid are {}".format(LEVEL, levelToName))
    
    def get_log_level(self):
        return self.level

    def color_log(self):
        return self.log
