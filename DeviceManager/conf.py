""" Service configuration module """

import os


class Config(object):
    """ Abstracts configuration, either retrieved from environment or from ctor arguments """
    def __init__(self,
                 db="dojot_devm",
                 dbhost="postgres",
                 dbuser="postgres",
                 dbpass=None,
                 dbdriver="postgresql+psycopg2",
                 create_db=True):
        self.dbname = os.environ.get('DBNAME', db)
        self.dbhost = os.environ.get('DBHOST', dbhost)
        self.dbuser = os.environ.get('DBUSER', dbuser)
        self.dbpass = os.environ.get('DBPASS', dbpass)
        self.dbdriver = os.environ.get('DBDRIVER', dbdriver)
        self.create_db = os.environ.get('CREATE_DB', create_db)

    def get_db_url(self):
        """ From the config, return a valid postgresql url """
        if self.dbpass is not None:
            return "%s://%s:%s@%s/%s" % (self.dbdriver, self.dbuser, self.dbpass,
                                         self.dbhost, self.dbname)
        else:
            return "%s://%s@%s/%s" % (self.dbdriver, self.dbuser, self.dbhost, self.dbname)


CONFIG = Config()
