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
        # Initialize the file if it doesn't exist
        if not os.path.exists(QUEUE_FILE):
            self._save_queue({})

    def _load_queue(self):
        with FileLock(LOCK_FILE):
            with open(QUEUE_FILE, 'r') as f:
                return json.load(f)

    def _save_queue(self, data):
        with FileLock(LOCK_FILE):
            with open(QUEUE_FILE, 'w') as f:
                json.dump(data, f, indent=4)

    def generate_job_id(self, url):
        # Parse the URL and strip ALL query parameters before hashing
        # This prevents duplicate jobs from e.g. LinkedIn tracking IDs
        parsed = urlparse(url)
        clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return hashlib.md5(clean_url.encode()).hexdigest()

    def add_job(self, title, company, url, source="linkedin"):
        queue = self._load_queue()
        job_id = self.generate_job_id(url)

        # Only add if we haven't seen this exact job before
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
            self._save_queue(queue)
            print(f"[QUEUE] [+] Added new job: {company} - {title}")
            return True
        return False

    def get_pending_jobs(self):
        queue = self._load_queue()
        return {jid: data for jid, data in queue.items() if data["status"] == "PENDING"}

    def update_status(self, job_id, new_status, notes=""):
        queue = self._load_queue()
        valid_statuses = ["PENDING", "APPLIED", "FAILED", "WORKDAY_SKIPPED", "URL_INVALID", "SOFT_FAIL"]
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")

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
            self._save_queue(queue)
        else:
            print(f"[QUEUE] [!] Error: Job ID {job_id} not found.")
