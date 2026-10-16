import { css, html, nothing } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import {
  createUpload,
  createVersion,
  uploadQuery,
} from '../../../../data/queries';
import type {
  AddonDistribution,
  FileUpload,
  ValidationMessage,
} from '../../../../data/types';
import {
  emit,
  errorBar,
  errorMessage,
  SubmissionStep,
} from '../submission-flow';
import '../../../../foundations/components/message-bar';
import { MAX_UPLOAD_SIZE } from '../../../../base';

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
    `,
  ];

  @query('moz-input-file') private input?: HTMLInputElement & {
    clear(): void;
  };

  @property() slug = '';
  @property() channel: AddonDistribution = 'listed';
  @property() uuid?: string;
  @state() private uploading = false;
  @state() private uploadError?: string;
  @state() private submitError?: string;

  #upload = uploadQuery(this, () => this.uuid ?? '');

  private isCurrentUpload(file: File) {
    return this.input?.files?.[0] === file;
  }

  reset() {
    this.uploading = false;
    this.uploadError = undefined;
    this.submitError = undefined;
    this.input?.clear();
  }

  protected get ready() {
    const upload = this.#upload().data;
    return Boolean(
      this.uuid && !this.uploading && upload?.processed && upload.valid,
    );
  }

  async submit(): Promise<boolean> {
    const upload = this.#upload().data;
    if (upload?.submitted) return true;
    if (!this.ready || !this.uuid || !upload) {
      this.submitError = 'Cannot upload invalid package.';
      return false;
    }
    try {
      const version = await createVersion(this.slug, this.uuid);
      emit(this, 'version-create', { id: version.id });
      return true;
    } catch (err) {
      this.input?.clear();
      this.submitError = errorMessage(err);
      return false;
    }
  }

  private async onFileChange() {
    const [file] = this.input?.files ?? [];
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
      upload = await createUpload(file, this.channel);
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
      </message-bar>
    `;
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
        accept=".zip,.xpi"
        max-size=${MAX_UPLOAD_SIZE}
        placeholder="Drag &amp; drop your package, or"
        ?disabled=${this.uploading}
        @change=${this.onFileChange}
      ></moz-input-file>

      ${errorBar('Could not upload version', this.submitError)}
      ${this.renderValidation()}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-upload': SubmitUpload;
  }
  interface HTMLElementEventMap {
    'version-create': CustomEvent<{ id: number }>;
    'upload-change': CustomEvent<{
      upload: FileUpload | undefined;
      uploading: boolean;
    }>;
  }
}
