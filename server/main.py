"""
this is the "secret sauce" -- a single entry-point that resolves the
import dependencies.  If you're using blueprints, you can import your
blueprints here too.

then when you want to run your app, you point to main.py or `main.app`
"""
from app import app, db
from db_models import *
from views import *

app.register_blueprint(blueprint)

if __name__ == '__main__':
    # create_tables()
    app.run(debug=True)
