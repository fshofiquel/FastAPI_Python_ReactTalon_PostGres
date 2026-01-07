# FastAPI + React + PostgreSQL User Management Application

A full-stack user management system built with FastAPI, React, and PostgreSQL. This project supports full CRUD operations, profile image uploads, automatic avatar generation with initials, and a clean, table-based UI.

## Features

- Create, read, update, and delete users
- FastAPI REST backend
- React frontend
- PostgreSQL database
- Profile image upload and storage
- Automatically generated avatar images when no image is uploaded
- Avatar background colors based on gender
- Initials rendered on avatars
- Images deleted from disk when users are deleted
- Clean table layout with edit/delete actions
- Gender color indicators

## Tech Stack

Backend:
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic
- Pillow (PIL)
- Uvicorn

Frontend:
- React
- Axios
- Tailwind CSS
- HTML5 Canvas

## Project Structure

FastAPI_Python_ReactTalon_PostGres/
├── backend/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── crud.py
│   ├── uploads/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.js
│   │   ├── index.js
│   │   ├── index.css
│   └── package.json
└── README.md

## Backend Setup

Create and activate a virtual environment:

python -m venv venv

Windows:
venv\Scripts\activate

Mac/Linux:
source venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Configure PostgreSQL in database.py:

postgresql://username:password@localhost:5432/database_name

Run the backend server:

uvicorn main:app --reload

Backend URL:
http://localhost:8000

## Frontend Setup

Navigate to the frontend directory:

cd frontend

Install dependencies:

npm install

Start the React app:

npm start

Frontend URL:
http://localhost:3000

## API Endpoints

GET /users/  
POST /users/  
PUT /users/{id}  
DELETE /users/{id}

## Profile Images and Avatars

- Uploaded images are stored in the uploads/ directory
- If no image is uploaded, an avatar is generated automatically
- Avatars contain user initials
- Avatar background color is determined by gender:
    - Male: Blue
    - Female: Pink
    - Other: Purple
- When a user is deleted, their profile image is also removed from disk

## User Fields

- id (auto-generated)
- full_name
- username
- password
- gender
- profile_pic

## Notes

- Passwords are stored as plain text for development purposes only
- Authentication is not included
- Intended for learning, demos, and portfolio use
