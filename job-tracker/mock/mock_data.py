# mock_data.py

MOCK_PROFILE = {
    "user_id": "9b4a6f2e-3c21-4a6a-9d1e-abc123456789",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@test.com",
    "resume_text": "Computer science student with experience in Python, React, and REST APIs.",
    "preferences": {
        "location": "New York",
        "job_type": "Software Engineer",
        "remote": True,
        "salary_min": 80000
    }
}

MOCK_JOBS = [
    {
        "id": "job-001",
        "title": "Junior Software Engineer",
        "company": "TechCorp",
        "location": "Remote",
        "description": "Looking for a Python developer with REST API experience.",
        "salary": 90000
    },
    {
        "id": "job-002",
        "title": "Frontend Developer",
        "company": "StartupXYZ",
        "location": "New York",
        "description": "React developer needed for fast-paced startup.",
        "salary": 85000
    },
    {
        "id": "job-003",
        "title": "Data Analyst",
        "company": "BigCo",
        "location": "Remote",
        "description": "Analyze datasets using Python and SQL.",
        "salary": 75000
    },
    # New jobs to test preferences
    {
        "id": "job-004",
        "title": "Backend Software Engineer",
        "company": "AlphaTech",
        "location": "New York",
        "description": "Looking for a backend developer with Python experience.",
        "salary": 95000,
        "remote": True
    },
    {
        "id": "job-005",
        "title": "Full Stack Software Engineer",
        "company": "BetaSoft",
        "location": "New York",
        "description": "Python, React, and REST API experience required.",
        "salary": 105000,
        "remote": False
    },
    {
        "id": "job-006",
        "title": "Mobile Developer",
        "company": "GammaApps",
        "location": "Boston",
        "description": "Develop iOS and Android apps using React Native.",
        "salary": 90000,
        "remote": True
    }
]