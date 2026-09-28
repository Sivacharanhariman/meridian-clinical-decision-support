import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { AdvisoryPanel } from '@/components/advisory-panel';
import { ActionsPanel } from '@/components/actions-panel';
import { emptyWorkspace, receiveSession, receiveResponse } from '@/lib/workspace-state';
import type { SessionView, TriageResponse } from '@/lib/types';
import rawSafety from './fixtures/safety.json';
import rawNormal from './fixtures/normal.json';
import rawRefusal from './fixtures/refusal.json';
import rawManual from './fixtures/manual.json';
const safety = rawSafety as SessionView;
const normal = rawNormal as SessionView;
const refusal = rawRefusal as SessionView;
const manual = rawManual as SessionView;
const noop = vi.fn();

describe('clinical display release gates', () => {
  it('never renders a disposition during unfinished analysis', () => {
    render(<AdvisoryPanel session={safety} response={safety.latestResponse} busy integrityError={null} />);
    expect(screen.queryByTestId('system-recommendation')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('after validation');
  });
  it('retains emergency styling and ED recommendation after refusal', () => {
    render(<AdvisoryPanel session={refusal} response={refusal.latestResponse} busy={false} integrityError={null} />);
    expect(screen.getByTestId('system-recommendation')).toHaveTextContent('Emergency department');
    expect(screen.getByTestId('system-recommendation').closest('.recommendation-card')).toHaveClass('danger');
    expect(screen.getByText('Recommended care declined by patient')).toBeInTheDocument();
  });
  it('keeps refusal separate from clinician override in the action display', () => {
    render(<ActionsPanel session={refusal} response={refusal.latestResponse} enabled busy={false} onAction={async()=>true} onAudit={noop} />);
    expect(screen.getByText('Declined by patient')).toBeInTheDocument();
    expect(screen.getByText('Remains home')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name:/Clinician override/})).not.toBeInTheDocument();
  });
  it('manual mode keeps escalation available and forbids accepting an unavailable synthesis', () => {
    render(<ActionsPanel session={manual} response={manual.latestResponse} enabled busy={false} onAction={async()=>true} onAudit={noop} />);
    expect(screen.getByRole('button', {name:/Accept recommendation/})).toBeDisabled();
    expect(screen.getByRole('button', {name:/Escalate to clinician/})).toBeEnabled();
  });
  it('a stale clinical response cannot replace what React renders', () => {
    const fresh = JSON.parse(JSON.stringify(safety.latestResponse)) as TriageResponse;
    fresh.sessionId = fresh.retrievalManifest.sessionId = normal.sessionId;
    fresh.stateVersion = fresh.recommendation.computedStateVersion = fresh.retrievalManifest.stateVersion = 2;
    const state = receiveSession(emptyWorkspace(1), normal, 1);
    const advanced = receiveResponse(state, fresh, 1);
    const stale = receiveResponse(advanced, normal.latestResponse!, 1);
    render(<AdvisoryPanel session={normal} response={stale.response} busy={false} integrityError={stale.integrityError} />);
    expect(screen.getByTestId('system-recommendation')).toHaveTextContent('Emergency department');
    expect(screen.queryByText('Clinician within 24 hours')).not.toBeInTheDocument();
  });
  it('equal-version conflicting content pauses the clinical display', () => {
    render(<AdvisoryPanel session={safety} response={safety.latestResponse} busy={false} integrityError="Integrity error: conflicting committed content" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Clinical display paused');
    expect(screen.queryByTestId('system-recommendation')).not.toBeInTheDocument();
  });
});
