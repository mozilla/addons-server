import { css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { uploadVersionSource, versionQuery } from '../../../../data/queries';
import { errorBar, errorMessage, SubmissionStep } from '../submission-flow';
import '../../../../components/not-found';
import '../../../../foundations/components/message-bar';
import { MAX_UPLOAD_SIZE } from '../../../../base';

const SOURCE_EXTENSIONS = '.zip,.tar.gz,.tgz,.tar.bz2';

const TRANSFORM_TOOLS = [
  'Code minifiers or obfuscators',
  'Bundlers like webpack, Rollup, or Vite',
  'Template engines or preprocessors',
  'Compilers like TypeScript or Sass',
  'Any step that transforms, combines, or generates files before you create the .zip',
];

@customElement('submit-source')
export class SubmitSource extends SubmissionStep {
  static styles = [
    SubmissionStep.styles,
    css`
    .subsection {
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
      padding: var(--space-large);
      border-radius: var(--border-radius-large);
      background-color: var(--color-gray-05);
    }
    ul {
      display: flex;
      flex-direction: column;
      margin: 0;
      gap: var(--space-medium);
      padding: var(--space-small);
      list-style: none;
    }
    li {
      display: flex;
      align-items: center;
      gap: var(--space-small);
      font-size: var(--font-size-xsmall);
    }
    li moz-icon {
      color: var(--color-gray-40);
      border: var(--space-xsmall) solid var(--color-gray-10);
      border-radius: 50%;
    }
    moz-visual-picker-item {
      --visual-picker-item-min-height: 0;
    }
    moz-input-file {
      width: 100%;
    }
  `,
  ];

  @property() slug = '';
  @property({ type: Number }) versionId?: number;
  @state() private usesTools?: boolean;
  @state() private file?: File;
  @state() private error?: string;

  #version = versionQuery(
    this,
    () => this.slug,
    () => this.versionId ?? 0,
  );

  protected get ready() {
    return this.usesTools === false || (this.usesTools === true && !!this.file);
  }

  async submit(): Promise<boolean> {
    if (!this.ready || !this.versionId) return false;
    if (!this.file) return true;

    try {
      await uploadVersionSource(this.slug, this.versionId, this.file);
      return true;
    } catch (err) {
      this.error = errorMessage(err);
      return false;
    }
  }

  private onFileChange(e: Event) {
    [this.file] = (e.target as HTMLInputElement).files ?? [];
    this.error = undefined;
  }

  private renderOption(usesTools: boolean, label: string, description: string) {
    const value = String(usesTools);
    return html`
      <moz-visual-picker
        variant="radio"
        orientation="vertical"
        .value=${this.usesTools === usesTools ? value : ''}
        @change=${() => (this.usesTools = usesTools)}
      >
        <moz-visual-picker-item
          value=${value}
          label=${label}
          description=${description}
        ></moz-visual-picker-item>
      </moz-visual-picker>
    `;
  }

  render() {
    const version = this.#version();
    if (version.isPending) return nothing;
    if (version.isError) return html`<not-found></not-found>`;
    return html`
      <submission-header
        label="Upload source code"
        description="Choose how this version will be distributed before you upload your package. If your add-on code is minified, bundled, generated, or transformed before packaging, upload the original source code for review. Reviewers use it to verify behavior and security, and may need rebuild instructions."
      ></submission-header>

      <div class="subsection">
        <submission-header
          label="Do you use tools that change your code before packaging?"
        ></submission-header>
        <ul>
          ${TRANSFORM_TOOLS.map(
            (label) => html`
              <li>
                <moz-icon name="information-fill"></moz-icon>
                <span>${label}</span>
              </li>
            `,
          )}
        </ul>
        ${this.renderOption(true, 'Yes', 'I use tools that change my code')}
        ${
          this.usesTools
            ? html`<moz-input-file
              name="source"
              accept=${SOURCE_EXTENSIONS}
              max-size=${MAX_UPLOAD_SIZE}
              placeholder="Drag &amp; drop your source archive, or"
              @change=${this.onFileChange}
            ></moz-input-file>`
            : nothing
        }
      </div>

      <div class="subsection">
        ${this.renderOption(
          false,
          'No',
          'The packaged files are the readable source code',
        )}
        ${
          this.usesTools === false
            ? html`<message-bar
                type="success"
                heading="No source upload needed"
                description="Based on your answer, you do not need to upload source for this version. If your workflow changes later, update this answer and upload source before your next submission."
              ></message-bar>`
            : nothing
        }
        ${errorBar('Upload failed', this.error)}
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-source': SubmitSource;
  }
}
