"""Generate UI test data from the actual API, never from hand-written DTOs."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings

output = Path(__file__).resolve().parents[1] / 'frontend/tests/fixtures'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as temporary:
    with TestClient(create_app(Settings(database_path=str(Path(temporary)/'fixtures.sqlite3')))) as client:
        token = client.post('/api/auth/demo', json={'actorId':'nurse-avery'}).json()['accessToken']
        client.headers['Authorization'] = 'Bearer ' + token
        for name, case in [('normal', 'normal-adult'), ('safety', 'chest-pain-ed'), ('manual', 'llm-timeout')]:
            session = client.post('/api/sessions', json={'caseId':case}).json()
            response = client.post('/api/triage', json={
                'sessionId':session['sessionId'], 'turnId':'ui-test-turn', 'baseStateVersion':0,
                'patientId':session['patient']['patientId'], 'patientDemographics':session['patient']['demographics'],
                'symptomDescription':session['originalTranscript'], 'nurseNotes':session['nurseNotes'],
            })
            response.raise_for_status()
            saved = client.get(f"/api/sessions/{session['sessionId']}").json()
            (output/f'{name}.json').write_text(json.dumps(saved, indent=2)+'\n')
            if name == 'safety':
                refused = client.post(f"/api/sessions/{session['sessionId']}/actions", json={
                    'actionId':'refusal-fixture', 'baseStateVersion':1,
                    'targetRecommendationId':response.json()['recommendation']['recommendationId'],
                    'actionType':'DOCUMENT_PATIENT_REFUSAL', 'rationale':'Synthetic informed refusal discussion recorded.',
                    'statedPreference':'Patient chooses to remain home in this synthetic scenario.',
                })
                refused.raise_for_status()
                (output/'refusal.json').write_text(json.dumps(refused.json(), indent=2)+'\n')
print('Exported API-generated frontend test fixtures.')
