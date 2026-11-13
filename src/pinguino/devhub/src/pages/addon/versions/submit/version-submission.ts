import { type RouteConfig, Routes } from '@lit-labs/router';
import { customElement, state } from 'lit/decorators.js';
import { BASE } from '../../../../base';
import {
  canSubmitListed,
  createVersion,
  getAddon,
  getVersions,
  hasIncompleteListing,
} from '../../../../data';
import type { Addon, Version } from '../../../../data/types';
import { navigateTo } from '../../../../utils/helper';
import { type StepId, SubmissionFlow } from '../../submit/submission-flow';

const PATHS = {
  source: 'source',
  details: 'listing',
  graphics: 'graphics',
  review: 'details',
  finish: 'finish',
} as const satisfies Partial<Record<StepId, string>>;
type VersionStep = keyof typeof PATHS;

@customElement('version-submission')
export class VersionSubmission extends SubmissionFlow {
  protected readonly heading = 'Submit a new version';
  protected readonly labels = {
    distribution: 'Add-on distribution',
    upload: 'Upload version',
  };

  @state() private addon?: Addon;
  @state() private hadListed = true;

  #lookedUp?: Promise<void>;
  #startOnDistribution = false;

  protected get kind() {
    return this.addon?.kind ?? 'extension';
  }

  protected get canSubmitListed() {
    return !this.addon || canSubmitListed(this.addon);
  }

  protected get showListingDetails() {
    return super.showListingDetails && !this.hadListed;
  }

  protected _routes: Routes = new Routes(
    this,
    [
      {
        path: '',
        enter: () => this.enterStart('upload'),
        render: () => this.uploadStep(),
      },
      {
        path: 'distribution',
        enter: () => this.enterStart('distribution'),
        render: () => this.distributionStep(),
      },
      this.pendingRoute('source', () => this.sourceStep()),
      this.pendingRoute('details', () => this.listingStep()),
      this.versionRoute('source', () => this.sourceStep()),
      this.versionRoute('details', () => this.listingStep()),
      this.versionRoute('graphics', () => this.imagesStep()),
      this.versionRoute('review', () => this.reviewStep()),
      this.versionRoute('finish', () => this.finishStep()),
    ],
    {
      fallback: {
        enter: () => this.goto(''),
      },
    },
  );

  protected async createFromUpload(uuid: string) {
    this.onCreate(await createVersion(this.addonSlug, uuid));
  }

  private pendingRoute(id: VersionStep, render: () => unknown): RouteConfig {
    return { path: PATHS[id], enter: () => this.enterPending(id), render };
  }

  private versionRoute(id: VersionStep, render: () => unknown): RouteConfig {
    return {
      path: `:versionId/${PATHS[id]}`,
      enter: (params) => this.enterVersion(params, id),
      render,
    };
  }

  private lookUp(versionId?: number) {
    this.#lookedUp ??= this.#lookUp(versionId);
    return this.#lookedUp;
  }

  async #lookUp(versionId?: number) {
    const fetched = await Promise.all([
      getAddon(this.addonSlug),
      getVersions(this.addonSlug),
    ]).catch(() => undefined);
    if (!fetched) return;
    const [addon, versions] = fetched;
    this.addon = addon;
    const current = versions.find((v) => v.id === versionId);
    this.hadListed = this.#hadListed(versions, current);
    if (current) {
      this.channel = current.channel;
      return;
    }
    // Continue on the last version's channel, if it's still allowed.
    const last = versions[0]?.channel;
    if (last && (last !== 'listed' || this.canSubmitListed)) {
      this.channel = last;
    } else {
      this.#startOnDistribution = true;
      this.channel = this.canSubmitListed ? 'listed' : 'unlisted';
    }
  }

  #hadListed(versions: Version[], current?: Version) {
    if (!this.addon?.channels?.includes('listed')) return false;
    if (current?.channel !== 'listed') return true;
    return versions.some((v) => v.channel === 'listed' && v !== current);
  }

  private async enterStart(id: 'upload' | 'distribution') {
    await this.lookUp();
    // A listed add-on still missing details has to finish them first.
    if (this.addon && hasIncompleteListing(this.addon)) {
      const slug = encodeURIComponent(this.addon.slug);
      return navigateTo(`${BASE}/addon/${slug}/submit/details`, {
        replace: true,
      });
    }
    const toDistribution = this.#startOnDistribution;
    this.#startOnDistribution = false;
    if (id === 'distribution') return this.enterStep(id);
    if (toDistribution) return this.goto('distribution');
    return this.enterStep(this.upload ? 'validation' : 'upload');
  }

  private async enterPending(id: VersionStep) {
    await this.lookUp();
    const href = this.steps[this.indexOf(id)]?.href;
    if (!this.upload || !href) return this.goto('');
    if (this.versionId) return navigateTo(href, { replace: true });
    return this.enterStep(id);
  }

  private async enterVersion(
    { versionId }: { versionId?: string },
    id: VersionStep,
  ) {
    this.versionId = Number(versionId);
    await this.lookUp(this.versionId);
    if (this.indexOf(id) < 0) {
      return this.goto(`${versionId}/${PATHS.review}`);
    }
    return this.enterStep(id);
  }

  private link(step: string) {
    const slug = encodeURIComponent(decodeURIComponent(this.addonSlug));
    return `${BASE}/addon/${slug}/versions/submit/${step}`;
  }

  protected stepHrefs() {
    const versionLink = (id: VersionStep) =>
      this.versionId ? this.link(`${this.versionId}/${PATHS[id]}`) : undefined;
    // The API does not take listed versions without required metadata.
    // Defer populating the URL with versionId until listing step,
    // i.e when it will actually exist.
    const pendingVersionLink = (id: VersionStep) =>
      versionLink(id) ??
      (this.showListingDetails ? this.link(PATHS[id]) : undefined);
    return {
      distribution: this.link('distribution'),
      upload: this.link(''),
      validation: this.link(''),
      source: pendingVersionLink('source'),
      details: pendingVersionLink('details'),
      graphics: versionLink('graphics'),
      review: versionLink('review'),
      finish: versionLink('finish'),
    };
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-submission': VersionSubmission;
  }
}
