import json
import os
import hashlib
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from filelock import FileLock

QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_queue.json")
LOCK_FILE = f"{QUEUE_FILE}.lock"

class JobQueue:
    def __init__(self):
        if not os.path.exists(QUEUE_FILE):
            with FileLock(LOCK_FILE):
                with open(QUEUE_FILE, 'w') as f:
                    json.dump({}, f, indent=4)

    def generate_job_id(self, url):
        parsed = urlparse(url)
        clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return hashlib.md5(clean_url.encode()).hexdigest()

    def add_job(self, title, company, url, source="linkedin"):
        job_id = self.generate_job_id(url)
        with FileLock(LOCK_FILE):
            try:
                with open(QUEUE_FILE, 'r') as f:
                    queue = json.load(f)
            except json.JSONDecodeError:
                print(f"[QUEUE] WARNING: Corrupted queue file. Resetting to empty.")
                queue = {}
            if job_id not in queue:
                queue[job_id] = {
                    "title": title,
                    "company": company,
                    "url": url,
                    "source": source,
                    "status": "PENDING",
                    "retries": 0,
                    "added_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "notes": ""
                }
                with open(QUEUE_FILE, 'w') as f:
                    json.dump(queue, f, indent=4)
                print(f"[QUEUE] [+] Added new job: {company} - {title}")
                return True
        return False

    def get_pending_jobs(self):
        with FileLock(LOCK_FILE):
            with open(QUEUE_FILE, 'r') as f:
                queue = json.load(f)
            return {jid: data for jid, data in queue.items() if data["status"] == "PENDING"}

    def update_status(self, job_id, new_status, notes=""):
        valid_statuses = ["PENDING", "APPLIED", "FAILED", "WORKDAY_SKIPPED", "URL_INVALID", "SOFT_FAIL", "FAILED_PRESCREEN"]
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")

        with FileLock(LOCK_FILE):
            with open(QUEUE_FILE, 'r') as f:
                queue = json.load(f)
                
            if job_id in queue:
                if new_status == "SOFT_FAIL":
                    queue[job_id]["retries"] = queue[job_id].get("retries", 0) + 1
                    if queue[job_id]["retries"] >= 3:
                        queue[job_id]["status"] = "FAILED"
                        queue[job_id]["notes"] = "Max retries exceeded. Terminal soft fail. " + notes
                        print(f"[QUEUE] [!] Job {job_id[:6]} exceeded 3 retries. Marked as FAILED.")
                    else:
                        queue[job_id]["status"] = "PENDING"
                        queue[job_id]["notes"] = f"Soft fail (Attempt {queue[job_id]['retries']}/3): {notes}"
                        print(f"[QUEUE] [~] Job {job_id[:6]} soft failed (Attempt {queue[job_id]['retries']}/3). Keeping PENDING.")
                else:
                    queue[job_id]["status"] = new_status
                    queue[job_id]["notes"] = notes
                    print(f"[QUEUE] [✓] Job {job_id[:6]} marked as {new_status}")
                    
                queue[job_id]["updated_at"] = datetime.now().isoformat()
                with open(QUEUE_FILE, 'w') as f:
                    json.dump(queue, f, indent=4)
            else:
                print(f"[QUEUE] [!] Error: Job ID {job_id} not found.")