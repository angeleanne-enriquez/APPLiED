# Local Setup Guide
This guide walks you through setting up the APPLiED Flask app locally, connecting to the database, and testing endpoints.  

---

## 1. Clone the Repository

Open your terminal and navigate to where you want the project:

```bash
cd ~/Desktop  # or wherever you want the folder
```

Clone the repo:

```bash
git clone https://github.com/angeleanne-enriquez/APPLiED.git
cd APPLiED
```

---

## 2. Set Up Python Virtual Environment

**Step 1**: Create a virtual environment
```bash
python3 -m venv venv
```

**Step 2**: Activate the virtual environment
```bash
source venv/bin/activate
```

**Step 3**: Install dependencies
```bash
pip install -r requirements.txt
```
---

## 3. Double Check Environment Variables

**Step 1**: The database URL should be:
```bash
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.ypbklqqbiuktuzwlsztu.supabase.co:5432/postgres
```

---

## 4. Run the Flask Server

```bash
python3 app.py
```

You should see:
```bash
 * Running on http://127.0.0.1:5001
```

## 5. Test Endpoints
**Step 1**: Health Check
```bash
curl http://127.0.0.1:5001/health
```

You should see:
```bash
{
  "status": "success",
  "message": "Server is running",
  "timestamp": "2026-02-08T23:11:21.123456"
}
```

**Step 2**: Database Check
```bash
curl http://127.0.0.1:5001/db
```

You should see:
```bash
{
  "status": "success",
  "message": "Database connected",
  "timestamp": "2026-02-08T23:12:45.123456"
}
```

**Step 3**: Submit User Into (with open for files)
- <name>_resume.txt → contains the resume text
- <name>_jobs.json → contains jobs wanted as a JSON array

```bash
curl -X POST http://127.0.0.1:5001/submit \
-H "Content-Type: application/json" \
-d '{
    "name": "Alice",
    "email": "alice@example.com",
    "resume_text": "Worked at XYZ, skills in Python",
    "jobs_wanted": "Backend, API"
}'
```

You should see (in terminal):
```bash
{
  "status": "success",
  "message": "User info submitted and files saved",
  "timestamp": "2026-02-08T23:15:01.123456"
}
```
And you should also see two additional files appear.

---

## 6. Fetch Remote Jobs from Remotive (tentative)

**Step 1**: Fetch jobs and store them in the database + `jobs.json`:

```bash
curl http://127.0.0.1:5001/fetch-jobs
```

You should see:
```bash
{
  "status": "success",
  "message": "Fetched and stored 25 jobs",
  "timestamp": "2026-02-09T00:00:35.914885"
}
```
