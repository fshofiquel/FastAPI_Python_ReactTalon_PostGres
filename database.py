import os
import sys
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from dotenv import load_dotenv, find_dotenv
import logging

logger = logging.getLogger(__name__)

# ==============================================================================
# ENVIRONMENT CONFIGURATION
# ==============================================================================

# Find and load .env file
env_file = find_dotenv()
if not env_file:
    print("❌ ERROR: No .env file found in project directory")
    print("Please create a .env file with the following variables:")
    print("  DATABASE_URL=postgresql://username:password@localhost:5432/database_name")
    print("\nExample .env file:")
    print("  DATABASE_URL=postgresql://user:pass@localhost:5432/mydb")
    sys.exit(1)

load_dotenv(env_file)
print(f"✅ Loaded environment from: {env_file}")

# ==============================================================================
# DATABASE URL VALIDATION
# ==============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL not set in .env file")
    print("\nYour .env file must contain:")
    print("  DATABASE_URL=postgresql://username:password@localhost:5432/database_name")
    print("\nExample:")
    print("  DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/user_management_db")
    sys.exit(1)

# Validate DATABASE_URL format
if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
    print("❌ ERROR: DATABASE_URL must start with 'postgresql://' or 'postgres://'")
    print(f"Current value: {DATABASE_URL}")
    print("\nCorrect format:")
    print("  postgresql://username:password@host:port/database_name")
    sys.exit(1)

# Log connection info (hide password)
try:
    # Extract host info for logging
    db_info = DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'unknown'
    print(f"✅ Database configuration validated")
    print(f"📊 Connecting to: {db_info}")
except Exception:
    print(f"✅ Database URL configured")

# ==============================================================================
# ENGINE CONFIGURATION
# ==============================================================================

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configure engine based on environment
if ENVIRONMENT == "production":
    # Production-optimized pool with connection management
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,                    # Maximum persistent connections
        max_overflow=10,                 # Maximum overflow connections
        pool_timeout=30,                 # Seconds to wait before timing out
        pool_recycle=3600,              # Recycle connections after 1 hour
        pool_pre_ping=True,             # Test connections before using
        echo=False,                      # Don't log SQL queries
        connect_args={
            "connect_timeout": 10,       # Connection timeout in seconds
            "options": "-c statement_timeout=30000"  # 30 second query timeout
        }
    )
    logger.info("🚀 Production database engine initialized")
    
elif ENVIRONMENT == "testing":
    # Testing configuration with verbose logging
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        echo=True,  # Log all SQL for debugging
    )
    logger.info("🧪 Testing database engine initialized")
    
else:
    # Development with moderate pooling and SQL logging
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,                     # Smaller pool for development
        max_overflow=5,
        pool_timeout=30,
        pool_pre_ping=True,              # Catch stale connections
        echo=True,                       # Log SQL queries for debugging
        connect_args={
            "connect_timeout": 10,
        }
    )
    logger.info("🔧 Development database engine initialized")

# ==============================================================================
# CONNECTION EVENT LISTENERS
# ==============================================================================

@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Log when new database connections are established"""
    logger.debug("📡 New database connection established")

@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when connections are checked out from pool"""
    logger.debug("🔄 Connection checked out from pool")

@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """Log when connections are returned to pool"""
    logger.debug("↩️  Connection returned to pool")

# ==============================================================================
# SESSION CONFIGURATION
# ==============================================================================

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# ==============================================================================
# DEPENDENCY INJECTION
# ==============================================================================

def get_db():
    """
    Database session dependency for FastAPI.
    
    This function provides a database session for each request and ensures
    proper cleanup even if errors occur during the request.
    
    Usage in FastAPI:
        @app.get("/users/")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    
    Yields:
        Session: Database session that will be automatically closed
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"❌ Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()
        logger.debug("Session closed")

# ==============================================================================
# HEALTH CHECK
# ==============================================================================

def check_database_health() -> bool:
    """
    Test database connectivity.
    
    This function attempts to connect to the database and execute a simple
    query to verify that the database is accessible and responding.
    
    Returns:
        bool: True if database is healthy, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database health check passed")
        return True
    except Exception as e:
        logger.error(f"❌ Database health check failed: {e}")
        return False

# ==============================================================================
# POOL STATISTICS
# ==============================================================================

def get_pool_stats() -> dict:
    """
    Get current connection pool statistics.
    
    Returns:
        dict: Pool statistics including size, connections in use, etc.
    """
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "total_connections": pool.size() + pool.overflow()
    }

# ==============================================================================
# STARTUP VALIDATION
# ==============================================================================

# Verify database connection on import
try:
    if check_database_health():
        print("✅ Database connection successful!")
    else:
        print("⚠️  Warning: Database health check failed")
        print("   Make sure PostgreSQL is running and credentials are correct")
except Exception as e:
    print(f"⚠️  Warning: Could not verify database connection: {e}")
    print("   The application may not work correctly")
