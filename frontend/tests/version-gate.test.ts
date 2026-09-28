import { describe, expect, it } from 'vitest';
import { advanceClinicalResponse, SessionGeneration } from '@/lib/version-gate';
import { emptyWorkspace, receiveResponse, receiveSession, hasCurrentRecommendation } from '@/lib/workspace-state';
import type { SessionView, TriageResponse } from '@/lib/types';
import raw from './fixtures/normal.json';
const session = raw as SessionView;
const current = session.latestResponse!;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
function atVersion(version: number): TriageResponse {
  const value = clone(current);
  value.stateVersion = value.recommendation.computedStateVersion = value.retrievalManifest.stateVersion = version;
  value.turnId = value.retrievalManifest.turnId = 'turn-' + version;
  value.responseId = 'response-' + version;
  return value;
}
describe('monotonic committed clinical response', () => {
  it('advances to a newer committed version', () => {
    expect(advanceClinicalResponse(current, atVersion(3), session.sessionId).kind).toBe('advanced');
  });
  it('drops an older response without replacing visible care', () => {
    const latest = atVersion(4);
    const result = advanceClinicalResponse(latest, current, session.sessionId);
    expect(result.kind).toBe('stale'); expect(result.response).toBe(latest);
  });
  it('permits an identical equal-version retry', () => {
    expect(advanceClinicalResponse(current, clone(current), session.sessionId).kind).toBe('replay');
  });
  it('canonicalizes object key order for retries', () => {
    const reordered = Object.fromEntries(Object.entries(current).reverse()) as TriageResponse;
    expect(advanceClinicalResponse(current, reordered, session.sessionId).kind).toBe('replay');
  });
  it.each(['turn', 'content', 'responseId'])('rejects equal-version changes to %s', change => {
    const changed = clone(current);
    if (change === 'turn') changed.turnId = changed.retrievalManifest.turnId = 'other-turn';
    if (change === 'content') changed.rationale[0].claim = 'An unvalidated replacement claim';
    if (change === 'responseId') changed.responseId = 'other-response';
    const result = advanceClinicalResponse(current, changed, session.sessionId);
    expect(result.kind).toBe('conflict'); expect(result.response).toBe(current);
  });
  it.each(['session', 'version', 'manifest', 'readiness'])('rejects inconsistent %s binding', field => {
    const changed = atVersion(2);
    if (field === 'session') changed.sessionId = 'wrong-session';
    if (field === 'version') changed.recommendation.computedStateVersion = 9;
    if (field === 'manifest') changed.retrievalManifest.turnId = 'wrong-turn';
    if (field === 'readiness') changed.recommendation.readinessState = 'READY';
    expect(advanceClinicalResponse(current, changed, session.sessionId).kind).toBe('conflict');
  });
  it('invalidates old promises after changing encounter or identity', () => {
    const generation = new SessionGeneration(); const first = generation.next(); const second = generation.next();
    expect(generation.isCurrent(first)).toBe(false); expect(generation.isCurrent(second)).toBe(true);
  });
});
describe('workspace and clinical versions remain distinct', () => {
  it('drops a delayed response from the prior encounter generation', () => {
    const state = receiveSession(emptyWorkspace(2), session, 2);
    expect(receiveResponse(state, atVersion(3), 1)).toBe(state);
  });
  it('a human action advances session state while preserving the clinical response', () => {
    const state = receiveSession(emptyWorkspace(1), session, 1);
    const afterAction = clone(session); afterAction.state.currentStateVersion = 2;
    const next = receiveSession(state, afterAction, 1);
    expect(next.session?.state.currentStateVersion).toBe(2);
    expect(next.response?.stateVersion).toBe(1);
    expect(hasCurrentRecommendation(next)).toBe(true);
  });
  it('blocks actions until a new response is joined to fresh session permissions', () => {
    const state = receiveSession(emptyWorkspace(1), session, 1);
    const next = receiveResponse(state, atVersion(2), 1);
    expect(hasCurrentRecommendation(next)).toBe(false);
  });
  it('pauses actions on an equal-version integrity conflict', () => {
    const state = receiveSession(emptyWorkspace(1), session, 1);
    const changed = clone(current); changed.responseId = 'replacement';
    const next = receiveResponse(state, changed, 1);
    expect(next.integrityError).toBeTruthy(); expect(hasCurrentRecommendation(next)).toBe(false);
  });
  it('drops old session snapshots after a human decision', () => {
    const afterAction = clone(session); afterAction.state.currentStateVersion = 3;
    const state = receiveSession(emptyWorkspace(1), afterAction, 1);
    expect(receiveSession(state, session, 1)).toBe(state);
  });
});
