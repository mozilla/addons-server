import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgreementState } from '../../../../src/data';
import { queryClient, queryKeys } from '../../../../src/data';
import * as queries from '../../../../src/data/queries';
import { DevhubAgreement } from '../../../../src/pages/addon/submit/templates/agreement';
import { mount, settle } from '../../../helpers/fixture';

const agreementState: AgreementState = {
  display_name: null,
  has_read_developer_agreement: false,
  last_developer_agreement_change: '2020-01-10T12:00:00',
};

async function mountAgreement(data: AgreementState) {
  queryClient.setQueryData(queryKeys.agreement, data);
  const el = await mount('devhub-agreement');
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

describe('devhub-agreement', () => {
  let acceptAgreement: ReturnType<typeof vi.spyOn>;
  let willUpdate: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    acceptAgreement = vi.spyOn(queries, 'acceptAgreement');
    willUpdate = vi.spyOn(DevhubAgreement.prototype, 'willUpdate');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows display name field when the account has none', async () => {
    const root = await mountAgreement(agreementState);
    expect(root.querySelector('#accept')).not.toBeNull();
    expect(root.querySelector('#display-name')).not.toBeNull();
  });

  it('hides display name field when one is already set', async () => {
    const root = await mountAgreement({
      ...agreementState,
      display_name: 'name',
    });
    expect(root.querySelector('#accept')).not.toBeNull();
    expect(root.querySelector('#display-name')).toBeNull();
  });

  it('accepts the agreement on submit', async () => {
    const root = await mountAgreement(agreementState);
    const form = root.querySelector('form');
  
    root.querySelector('#display-name').value = 'new_name';
    form.dispatchEvent(new Event('submit', { cancelable: true }));

    await vi.waitFor(() => expect(acceptAgreement).toHaveBeenCalledOnce());
    expect(acceptAgreement).toHaveBeenCalledWith({
      display_name: 'new_name',
      last_developer_agreement_change:
        agreementState.last_developer_agreement_change,
    });

    // Can only submit once.
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(acceptAgreement).toHaveBeenCalledOnce();
  });

  it('redirects if user has already accepted the agreement', async () => {
    expect(willUpdate).not.toHaveBeenCalled();
    await mountAgreement({
      ...agreementState,
      has_read_developer_agreement: true,
    });
    expect(willUpdate).toHaveBeenCalledOnce();
  });
});
