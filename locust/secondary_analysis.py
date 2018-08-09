import json
import os
import time
from collections import deque
from configparser import ConfigParser

import requests
from locust import TaskSet, HttpLocust, task

AUTH_BROKER_URL = 'https://danielvaughan.eu.auth0.com/oauth/token'

BASE_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
FILE_DIRECTORY = f'{BASE_DIRECTORY}/files/secondary_analysis'

_config = ConfigParser()
_secret_file_path = os.path.join(BASE_DIRECTORY, 'secrets.ini')
_config.read(_secret_file_path)


def secret_default(secret):
    return _config.get('default', secret, fallback=None)


class Resource(object):

    _links = None

    def __init__(self, links):
        self._links = links

    def get_link(self, path):
        return self._links[path]['href']


class ResourceQueue:

    _queue = deque()

    def queue(self, resource: Resource):
        self._queue.append(resource)

    def wait_for_resource(self):
        submission = self._queue.popleft() if len(self._queue) > 0 else None
        while not submission:
            time.sleep(0.5)
            submission = self._queue.popleft() if len(self._queue) > 0 else None
        return submission


_submission_queue = ResourceQueue()
_analysis_queue = ResourceQueue()


class SecondarySubmission(TaskSet):

    _access_token = None

    _dummy_analysis_details = None

    def on_start(self):
        with open(f'{FILE_DIRECTORY}/analysis.json') as analysis_file:
            self._dummy_analysis_details = json.load(analysis_file)
        self._access_token = secret_default('access_token')

    @task
    def setup_analysis(self):
        submission = self._create_submission()
        if submission:
            processes_link = submission.get_link('processes')
            self._add_analysis_to_submission(processes_link)

    def _create_submission(self) -> Resource:
        headers = {'Authorization': f'Bearer {self._access_token}'}
        response = self.client.post('/submissionEnvelopes', headers=headers, json={},
                                    name='create new submission')
        response_json = response.json()
        links = response_json.get('_links')
        submission = None
        if links:
            submission = Resource(links)
            _submission_queue.queue(submission)
        return submission

    def _add_analysis_to_submission(self, processes_link):
        response = self.client.post(processes_link, json=self._dummy_analysis_details,
                                    name='add analysis to submission')
        analysis_json = response.json()
        links = analysis_json.get('_links')
        if links:
            _analysis_queue.queue(Resource(links))


class Validation(TaskSet):

    @task
    def validate_analysis(self):
        analysis = _analysis_queue.wait_for_resource()
        analysis_link = f"{analysis.get_link('self')}"
        self.client.patch(analysis_link, json={'validationErrors': []},
                          name='report validation errors')
        self.client.patch(analysis_link, json={'validationState': 'VALID'},
                          name='set validation status')


class GreenBox(HttpLocust):
    task_set = SecondarySubmission


class Validator(HttpLocust):
    task_set = Validation