from sqlalchemy.orm import Session
from passlib.context import CryptContext
import models, schemas

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)



def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_user(db: Session, user: schemas.UserCreate, profile_pic: str | None = None):
    hashed_password = get_password_hash(user.password)

    db_user = models.User(
        full_name=user.full_name,
        username=user.username,
        password=hashed_password,
        gender=user.gender,
        profile_pic=profile_pic,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def update_user(
        db: Session,
        user_id: int,
        user: schemas.UserCreate,
        profile_pic: str | None = None,
):
    db_user = get_user(db, user_id)
    if not db_user:
        return None

    db_user.full_name = user.full_name
    db_user.username = user.username
    db_user.gender = user.gender

    if profile_pic:
        db_user.profile_pic = profile_pic

    if user.password:
        db_user.password = get_password_hash(user.password)

    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int):
    db_user = get_user(db, user_id)
    if not db_user:
        return None

    db.delete(db_user)
    db.commit()
    return db_user
