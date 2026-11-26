import type { RouteConfig, Routes } from '@lit-labs/router';
import { customElement, state } from 'lit/decorators.js';
import { BASE } from '../../../../base';
import {
  canSubmitListed,
  createVersion,
  getAddon,
  getUpload,
  getVersion,
  getVersions,
  hasIncompleteListing,
} from '../../../../data';
import type { Addon, Version } from '../../../../data/types';
import { createRoutes, navigateTo } from '../../../../utils/helper';
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
  #adopting?: Promise<void>;

  protected get kind() {
    return this.addon?.kind ?? 'extension';
  }

  protected get canSubmitListed() {
    return !this.addon || canSubmitListed(this.addon);
  }

  protected get showListingDetails() {
    return super.showListingDetails && !this.hadListed;
  }

  protected _routes: Routes = createRoutes(
    this,
    [
      {
        path: '',
        enter: () => this.enterStart('distribution'),
        render: () => this.distributionStep(),
      },
      {
        path: 'upload',
        enter: () => this.enterStart('upload'),
        render: () => this.uploadStep(),
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
    const [addon, { items: versions }] = fetched;
    this.addon = addon;
    const current = versionId
      ? await getVersion(this.addonSlug, versionId, versions)
      : undefined;
    this.hadListed = this.#hadListed(versions, current);
    if (current) {
      this.channel = current.channel;
      return;
    }
    // Pre-select the distribution picker with the last version's channel if it's
    // still allowed, else the first allowed channel.
    const last = versions[0]?.channel;
    if (last && (last !== 'listed' || this.canSubmitListed)) {
      this.channel = last;
    } else {
      this.channel = this.canSubmitListed ? 'listed' : 'unlisted';
    }
  }

  #hadListed(versions: Version[], current?: Version) {
    if (!this.addon?.channels?.includes('listed')) return false;
    if (current?.channel !== 'listed') return true;
    return versions.some((v) => v.channel === 'listed' && v !== current);
  }

  private async enterStart(id: 'upload' | 'distribution') {
    const carried = this.takeCarriedUpload();
    // The router can enter twice at once; both have to wait for the upload.
    if (carried) this.#adopting = this.adoptUpload(carried);
    await this.lookUp();
    await this.#adopting;
    // A listed add-on still missing details has to finish them first.
    if (this.addon && hasIncompleteListing(this.addon)) {
      const slug = encodeURIComponent(this.addon.slug);
      return navigateTo(`${BASE}/addon/${slug}/submit/details`, {
        replace: true,
      });
    }
    if (id === 'distribution') return this.enterStep(id);
    return this.enterStep(this.upload ? 'validation' : 'upload');
  }

  // A package uploaded as a new add-on whose ID turned out to be this one's
  // comes over as `?upload=<uuid>`, so it doesn't have to be uploaded again.
  private takeCarriedUpload() {
    const url = new URL(location.href);
    const uuid = url.searchParams.get('upload');
    if (!uuid) return undefined;
    url.searchParams.delete('upload');
    window.history.replaceState(window.history.state, '', url);
    return uuid;
  }

  private async adoptUpload(uuid: string) {
    await this.lookUp();
    if (this.upload) return;
    const upload = await getUpload(uuid, this.addonSlug).catch(() => undefined);
    if (!upload) {
      this.uploadNotice = "That file couldn't be loaded. Upload it again.";
      return;
    }
    if (upload.submitted) {
      this.uploadNotice = 'That file has already been submitted.';
      return;
    }
    // Its channel was picked when it was uploaded. If this add-on can't take
    // it, the upload's validation says why.
    this.channel = upload.channel;
    this.setUpload(upload);
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
      distribution: this.link(''),
      upload: this.link('upload'),
      validation: this.link('upload'),
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
