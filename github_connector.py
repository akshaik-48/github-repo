from github import Github

class GitHubConnector:
    def __init__(self, token: str):
        self.client = Github(token)
