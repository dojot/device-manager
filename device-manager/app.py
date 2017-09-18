import json
import os
from flask import Flask
from templateManager import template
from deviceManager import device

app = Flask(__name__)
app.register_blueprint(device)
app.register_blueprint(template)

if __name__ == '__main__':
    app.run(threaded=True)
