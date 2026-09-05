from app.database.session import engine, Base
import app.models # Register all models with Base

def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Database tables initialized successfully.")
