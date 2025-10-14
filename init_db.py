import os
import pymysql
from flask import g
from dotenv import load_dotenv
from utils import logger
# Load environment variables
load_dotenv()

# Default MySQL connection details
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# Make connection
def get_db():
    if "db" not in g:
        try:
            g.db = pymysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                port=DB_PORT,
                cursorclass=pymysql.cursors.DictCursor,
                charset='utf8mb4',
            )
        except pymysql.MySQLError as e:
            print(f"MySQL connection error: {e}")
            g.db = None
            raise
    return g.db

def close_db(e=None):
    """Close the database connection at the end of request if it exists."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    """Initialize the database using schema from db_init.sql."""
    db = get_db()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sql_path = os.path.join(script_dir, "db_init.sql")

    with open(sql_path, "r") as f:
        sql_script = f.read()

    with db.cursor() as cursor:
        for statement in sql_script.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt)
    db.commit()

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Clear existing data and create new tables."""
        init_db()
        logger.info("MySQL database initialized successfully!")
