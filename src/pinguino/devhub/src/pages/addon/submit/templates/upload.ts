import type { InputFileRejectedDetail } from '@mozilla/lit-web-components';
import { css, html, nothing } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { createUpload, uploadQuery } from '../../../../data/queries';
import { APP_NAMES } from '../../../../data/statuses';
import type {
  AddonDistribution,
  CompatibleApp,
  FileUpload,
  ValidationMessage,
} from '../../../../data/types';
import { emit, formatFileSize } from '../../../../utils/helper';
import {
  errorBar,
  errorMessage,
  rejectMessage,
  SubmissionStep,
} from '../submission-step';
import '../../../../foundations/components/message-bar';
import { BASE, MAX_UPLOAD_SIZE, PACKAGE_EXTENSIONS } from '../../../../base';

const PACKAGE_HINT = `Max ${formatFileSize(MAX_UPLOAD_SIZE)} · ${PACKAGE_EXTENSIONS.join(', ')}`;
const APPS = Object.keys(APP_NAMES) as CompatibleApp[];

@customElement('submit-upload')
export class SubmitUpload extends SubmissionStep {
  static styles = [
    SubmissionStep.styles,
    css`
      moz-input-file {
        width: 100%;
      }
      .messages {
        display: flex;
        flex-direction: column;
        gap: var(--space-small);
      }
      .file {
        color: var(--text-color-deemphasized);
        font-size: var(--font-size-small);
        margin: var(--space-xsmall) 0 0 0;
      }
      .apps {
        display: flex;
        flex-direction: column;
        gap: var(--space-small);
      }
      .apps .error {
        color: var(--text-color-error);
        margin: 0;
      }
    `,
  ];

  @query('moz-input-file') private input?: HTMLInputElement & {
    clear(): void;
  };

  @property() channel: AddonDistribution = 'listed';
  @property({ attribute: false }) create: (uuid: string) => Promise<void> =
    async () => {};
  @property() uuid?: string;
  @property() versionOf?: string;
  // Why an upload handed over from elsewhere couldn't be used.
  @property() notice?: string;
  @property({ attribute: false }) defaultApps: CompatibleApp[] = ['firefox'];
  @state() private apps?: CompatibleApp[];
  @state() private uploading = false;
  @state() private uploadError?: string;
  @state() private submitError?: string;

  #upload = uploadQuery(
    this,
    () => this.uuid ?? '',
    () => this.versionOf ?? '',
  );

  private isCurrentUpload(file: File) {
    return this.input?.files?.[0] === file;
  }

  reset() {
    this.apps = undefined;
    this.uploading = false;
    this.uploadError = undefined;
    this.submitError = undefined;
    this.input?.clear();
  }

  protected get ready() {
    const upload = this.#upload().data;
    return Boolean(
      this.uuid &&
        !this.uploading &&
        upload?.processed &&
        upload.valid &&
        this.compatibility?.length !== 0,
    );
  }

  // Undefined until there's a valid extension: the API refuses custom
  // compatibility for dictionaries, and Android for language packs.
  get compatibility(): CompatibleApp[] | undefined {
    const manifest = this.#upload().data?.manifest_data;
    if (manifest?.type !== 'extension') return undefined;
    return APPS.filter(
      (app) =>
        this.#picked.includes(app) ||
        (app === 'android' && this.#androidLocked),
    );
  }

  get #picked() {
    return this.apps ?? this.defaultApps;
  }

  get #androidLocked() {
    return Boolean(
      this.#upload().data?.manifest_data?.explicitly_compatible_with_android,
    );
  }

  async submit(): Promise<boolean> {
    const upload = this.#upload().data;
    if (upload?.submitted) return true;
    if (this.compatibility?.length === 0) {
      this.submitError = 'Select at least one application.';
      return false;
    }
    if (!this.ready || !this.uuid || !upload) {
      this.submitError = 'Cannot upload invalid package.';
      return false;
    }
    try {
      await this.create(this.uuid);
      return true;
    } catch (err) {
      this.input?.clear();
      this.submitError = errorMessage(err);
      return false;
    }
  }

  // Clearing fires a change, which resets the step and wipes any earlier
  // error, so the rejection has to be recorded after that.
  private onFileReject(e: CustomEvent<InputFileRejectedDetail>) {
    this.input?.clear();
    this.uploadError = rejectMessage(e.detail);
  }

  private async onFileChange() {
    const [file] = this.input?.files ?? [];
    this.apps = undefined;
    this.uploadError = undefined;
    this.submitError = undefined;
    emit(this, 'upload-change', {
      upload: undefined,
      uploading: Boolean(file),
    });
    if (!file) {
      this.uploading = false;
      return;
    }

    this.uploading = true;
    let upload: FileUpload | undefined;
    let error: unknown;
    try {
      upload = await createUpload(file, this.channel, this.versionOf);
    } catch (err) {
      error = err;
    }
    if (!this.isCurrentUpload(file)) return;
    this.uploading = false;
    if (upload) {
      emit(this, 'upload-change', { upload, uploading: false });
    } else {
      this.input?.clear();
      this.uploadError = errorMessage(error);
    }
  }

  private renderMessage(message: ValidationMessage) {
    const type = message.type === 'notice' ? 'info' : message.type;
    const location = message.file
      ? `${message.file}${message.line ? `:${message.line}` : ''}`
      : '';
    return html`
      <message-bar type=${type} heading=${message.message}>
        ${message.description}
        ${location ? html`<p class="file">${location}</p>` : nothing}
        ${this.renderNewVersionLink(message)}
      </message-bar>
    `;
  }

  private renderNewVersionLink({ addon }: ValidationMessage) {
    if (!addon || !this.uuid) return nothing;
    const params = new URLSearchParams({ upload: this.uuid });
    const href = `${BASE}/addon/${encodeURIComponent(addon.slug)}/versions/submit/upload?${params}`;
    return html`<p>
      <a href=${href}>Submit this file as a new version of ${addon.name}</a>
    </p>`;
  }

  private renderCompatibility() {
    const selected = this.compatibility;
    if (!selected) return nothing;
    return html`
      <submission-header
        label="Compatibility"
        description="Which applications is this version compatible with?"
      ></submission-header>
      <div class="apps">
        ${APPS.map((app) => {
          const locked = app === 'android' && this.#androidLocked;
          return html`<moz-checkbox
            label=${APP_NAMES[app]}
            description=${
              locked
                ? 'Explicitly marked as compatible with Firefox for Android in the manifest.'
                : nothing
            }
            ?checked=${selected.includes(app)}
            ?disabled=${locked}
            @change=${(e: Event) =>
              this.toggleApp(app, (e.target as HTMLInputElement).checked)}
          ></moz-checkbox>`;
        })}
        ${
          selected.length
            ? nothing
            : html`<p class="error">Select at least one application.</p>`
        }
      </div>
    `;
  }

  private toggleApp(app: CompatibleApp, checked: boolean) {
    this.apps = checked
      ? [...this.#picked, app]
      : this.#picked.filter((other) => other !== app);
  }

  private renderValidation() {
    if (this.uploadError) return errorBar('Upload failed', this.uploadError);
    const upload = this.#upload().data;
    if (!this.uuid || !upload || this.submitError) return nothing;
    if (!upload.processed) {
      return html`<message-bar
        type="info"
        heading="Validating..."
      ></message-bar>`;
    }
    return html`
      <submission-header label="Validation"></submission-header>
      <div class="messages">
        ${upload.validation ? upload.validation.messages.map((m) => this.renderMessage(m)) : 'No errors found.'}
      </div>
    `;
  }

  render() {
    return html`
      <submission-header
        label="Upload version"
        description="Use the fields below to upload your add-on package. After upload, a series of automated validation tests will be run on your file. The maximum file size accepted is 200.0 MB. If your add-on is larger than 200.0 MB, it will fail validation."
      ></submission-header>
      <moz-input-file
        name="package"
        accept=${PACKAGE_EXTENSIONS.join(',')}
        max-size=${MAX_UPLOAD_SIZE}
        placeholder="Drag &amp; drop your package, or"
        ?disabled=${this.uploading}
        @change=${this.onFileChange}
        @moz-input-file:rejected=${this.onFileReject}
      >
        <span slot="hint">${PACKAGE_HINT}</span>
      </moz-input-file>

      ${errorBar('Could not use that upload', this.notice)}
      ${errorBar('Could not upload version', this.submitError)}
      ${this.renderValidation()}
      ${this.renderCompatibility()}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-upload': SubmitUpload;
  }
  interface HTMLElementEventMap {
    'upload-change': CustomEvent<{
      upload: FileUpload | undefined;
      uploading: boolean;
    }>;
  }
}
