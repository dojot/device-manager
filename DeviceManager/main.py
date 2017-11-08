from app import app

# initialize modules
import DeviceManager
import TemplateManager
import ErrorManager

if __name__ == '__main__':
    app.run(host='0.0.0.0', threaded=True)
