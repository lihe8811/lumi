/**
 * @license
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import "../../pair-components/textarea";
import "../../pair-components/icon";
import "../../pair-components/icon_button";
import "../lumi_image/lumi_image";

import { MobxLitElement } from "@adobe/lit-mobx";
import { CSSResultGroup, html, nothing, PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { classMap } from "lit/directives/class-map.js";

import { core } from "../../core/core";
import { HomeService } from "../../services/home.service";
import { HistoryService } from "../../services/history.service";
import {
  Pages,
  RouterService,
  getLumiPaperUrl,
} from "../../services/router.service";
import { SnackbarService } from "../../services/snackbar.service";
import { BackendApiService } from "../../services/backend_api.service";

import {
  LumiDoc,
  LoadingStatus,
  ArxivMetadata,
  LOADING_STATUS_ERROR_STATES,
} from "../../shared/lumi_doc";
import { ArxivCollection } from "../../shared/lumi_collection";
import { extractArxivId } from "../../shared/string_utils";

import { styles } from "./home_gallery.scss";
import { makeObservable, observable, ObservableMap, toJS } from "mobx";
import { PaperData } from "../../shared/types_local_storage";
import { MAX_IMPORT_URL_LENGTH, DEFAULT_COVER_IMAGE_PATH } from "../../shared/constants";
import { GalleryView } from "../../shared/types";
import { ifDefined } from "lit/directives/if-defined.js";
import { DialogService, TOSDialogProps } from "../../services/dialog.service";
import { SettingsService } from "../../services/settings.service";

function getStatusDisplayText(status: LoadingStatus) {
  switch (status) {
    case LoadingStatus.WAITING:
      return "Loading";
    case LoadingStatus.SUMMARIZING:
      return "Summarizing";
    default:
      return "";
  }
}

/** Gallery for home/landing page */
@customElement("home-gallery")
export class HomeGallery extends MobxLitElement {
  static override styles: CSSResultGroup = [styles];

  private readonly dialogService = core.getService(DialogService);
  private readonly homeService = core.getService(HomeService);
  private readonly routerService = core.getService(RouterService);
  private readonly backendApiService = core.getService(BackendApiService);
  private readonly historyService = core.getService(HistoryService);
  private readonly snackbarService = core.getService(SnackbarService);
  private readonly settingsService = core.getService(SettingsService);

  @property() galleryView: GalleryView = GalleryView.LOCAL;

  // Paper URL or ID for text input box
  @state() private paperInput: string = "";
  // Whether the last imported paper is still loading metadata
  // (if true, this blocks importing another paper)
  @state() private isLoadingMetadata = false;

  private loadingStatusMap = new ObservableMap<string, LoadingStatus>();
  @observable.shallow private pendingJobs = new ObservableMap<string, string>();

  constructor() {
    super();
    makeObservable(this);
  }

  get isLoadingDocument(): boolean {
    return this.pendingJobs.size > 0 || this.isLoadingMetadata;
  }

  override disconnectedCallback() {
    super.disconnectedCallback();
    this.pendingJobs.clear();
  }

  protected override firstUpdated(_changedProperties: PropertyValues): void {
    if (!this.settingsService.isTosConfirmed.value) {
      this.dialogService.show(
        new TOSDialogProps(() => {
          this.dialogService.hide(new TOSDialogProps(() => {}));
        })
      );
    }
    this.loadExistingPapers();
  }

  private async loadExistingPapers() {
    try {
      const resp = await this.backendApiService.listPapers();
      resp.papers.forEach((paper) => {
        const metadata = paper.metadata as ArxivMetadata | undefined;
        if (metadata && !metadata.paperId) {
          metadata.paperId = paper.arxiv_id;
        }
        if (metadata && !metadata.version) {
          metadata.version = paper.version;
        }
        if (metadata) {
          this.historyService.addPaper(paper.arxiv_id, metadata);
          this.loadingStatusMap.set(paper.arxiv_id, LoadingStatus.SUCCESS);
        }
      });
    } catch (e) {
      console.error("Failed to load existing papers:", e);
    }
  }

  private async loadDocument() {
    // Extract arXiv ID from potential paper link
    const paperId = extractArxivId(this.paperInput);
    if (!paperId) {
      // Paper ID is only empty if input was empty or invalid
      this.snackbarService.show(`Error: Invalid arXiv URL or ID`);
      return;
    }

    this.isLoadingMetadata = true;
    let metadata: ArxivMetadata | null = null;
    try {
      const metaResp = await this.backendApiService.getMetadata(paperId);
      metadata = metaResp.metadata as ArxivMetadata;
      metadata.paperId = paperId;
    } catch (e) {
      // Metadata may not exist yet; proceed to request import.
    }

    const existingPapers = this.historyService.getPaperHistory();
    const foundPaper = existingPapers.find(
      (paper) => paper.metadata.paperId === paperId
    );
    if (foundPaper && foundPaper.status === "complete") {
      this.snackbarService.show("Paper already loaded.");
    }

    let jobId: string;
    try {
      const resp = await this.backendApiService.requestImport(paperId);
      jobId = resp.job_id;
    } catch (error) {
      this.snackbarService.show(`Error: ${(error as Error).message}`);
      this.isLoadingMetadata = false;
      return;
    } finally {
      this.isLoadingMetadata = false;
    }

    // Reset paper input
    this.paperInput = "";

    if (metadata) {
      this.historyService.addLoadingPaper(paperId, metadata);
    }
    this.pendingJobs.set(paperId, jobId);
    this.loadingStatusMap.set(paperId, LoadingStatus.WAITING);
    this.pollJob(paperId, jobId);
  }

  private async pollJob(paperId: string, jobId: string) {
    const maxAttempts = 120;
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const status = await this.backendApiService.jobStatus(jobId);
        this.loadingStatusMap.set(paperId, status.status as LoadingStatus);
        if (status.status === LoadingStatus.SUCCESS) {
          const version = status.version ?? "1";
          const docResp = await this.backendApiService.getLumiDoc(
            paperId,
            version
          );
          const lumiDoc = docResp.doc as LumiDoc;
          lumiDoc.summaries = docResp.summaries;
          this.historyService.addPaper(paperId, lumiDoc.metadata as ArxivMetadata);
      // Metadata already available via backend; no extra load.
          this.pendingJobs.delete(paperId);
          this.snackbarService.show("Document loaded.");
          return;
        }
        if (
          LOADING_STATUS_ERROR_STATES.includes(
            status.status as LoadingStatus
          ) ||
          status.status === LoadingStatus.TIMEOUT
        ) {
          this.historyService.deletePaper(paperId);
          this.pendingJobs.delete(paperId);
          this.snackbarService.show(`Error loading document: ${status.status}`);
          return;
        }
      } catch (e) {
        console.error("Error polling job status:", e);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    this.pendingJobs.delete(paperId);
    this.snackbarService.show("Timed out waiting for document import.");
  }

  override render() {
    return html`${this.renderContent()}${this.renderDialog()}`;
  }

  private renderContent() {
    const historyItems = this.historyService
      .getPaperHistory()
      .map((item) => item.metadata)
      .filter((m): m is ArxivMetadata => !!m);

    return html`
      ${this.renderLoadingMessages(historyItems)}
      ${this.renderCollection(historyItems)}
    `;
  }

  // TODO: Move document loading logic to MobXService and move this dialog
  // to app.ts
  private renderDialog() {
    if (!this.homeService.showUploadDialog) {
      return nothing;
    }

    const autoFocus = () => {
      // Only auto-focus chat input if on desktop
      return navigator.maxTouchPoints === 0;
    };

    const close = () => {
      this.homeService.setShowUploadDialog(false);
    };

    const submit = () => {
      this.routerService.navigate(Pages.HOME);
      this.loadDocument();
      close();
    };

    return html`
      <pr-dialog
        .showDialog=${this.homeService.showUploadDialog}
        .onClose=${close}
        showCloseButton
        enableEscape
      >
        <div slot="title">Import paper</div>
        <div class="dialog-content">
          <div class="paper-input">
            <pr-textarea
              ?disabled=${this.isLoadingMetadata}
              ?focused=${autoFocus}
              size="medium"
              .value=${this.paperInput}
              .maxLength=${MAX_IMPORT_URL_LENGTH}
              @change=${(e: CustomEvent) => {
                this.paperInput = e.detail.value;
              }}
              @keydown=${(e: CustomEvent) => {
                if (e.detail.key === "Enter") {
                  submit();
                }
              }}
              placeholder="Paste your arXiv paper link here"
            ></pr-textarea>
            <pr-icon-button
              icon="arrow_forward"
              variant="tonal"
              @click=${submit}
              .loading=${this.isLoadingMetadata}
              ?disabled=${this.isLoadingMetadata || !this.paperInput}
            >
            </pr-icon-button>
          </div>
        </div>
      </pr-dialog>
    `;
  }

  private renderLoadingMessages(metadata: ArxivMetadata[]) {
    const loadingItems = metadata.filter((item) =>
      this.pendingJobs.has(item.paperId)
    );

    const renderNewLoading = () => {
      return html`
        <div class="loading-message"><i>Loading new paper...</i></div>
      `;
    };

    if (loadingItems.length > 0) {
      return html`
        <div class="loading-section">
          ${this.isLoadingMetadata ? renderNewLoading() : nothing}
          ${loadingItems.map(
            (item) => html`
              <div class="loading-message">
                Loading <i>${item.title} (${item.paperId})</i>
              </div>
            `
          )}
        </div>
      `;
    } else if (this.isLoadingMetadata) {
      return html` <div class="loading-section">${renderNewLoading()}</div> `;
    }
    return nothing;
  }

  private getImageUrl() {
    return async (path: string) => {
      if (path.startsWith("assets/")) {
        const prefix = (process.env.URL_PREFIX ?? "/").replace(/\/+$/, "");
        const assetPath = path.startsWith("/") ? path : `/${path}`;
        return `${prefix}${assetPath}`;
      }
      return this.backendApiService.signUrl(path, "get");
    };
  }

  private renderCollection(items: ArxivMetadata[]) {
    const renderItem = (metadata: ArxivMetadata) => {
      if (!metadata) {
        return nothing;
      }

      const stored = this.historyService.getPaperData(metadata.paperId);
      const isUnread = !stored?.openedTimestamp;
      const isRecent =
        !!stored?.addedTimestamp &&
        Date.now() - stored.addedTimestamp < 24 * 60 * 60 * 1000;
      const showNewBadge = stored?.status === "complete" && isUnread && isRecent;

      const featuredImage = (metadata as any)?.featuredImage;
      const imagePath =
        featuredImage?.imageStoragePath ||
        featuredImage?.image_storage_path ||
        (metadata as any)?.featured_image?.image_storage_path ||
        DEFAULT_COVER_IMAGE_PATH;
      const status = this.loadingStatusMap.get(metadata.paperId);
      return html`
        <a
          href=${getLumiPaperUrl(metadata.paperId)}
          class="paper-card-link"
          rel="noopener noreferrer"
        >
          <paper-card
            .status=${status ? getStatusDisplayText(status) : ""}
            .metadata=${metadata}
            .image=${ifDefined({ image_storage_path: imagePath })}
            .getImageUrl=${this.getImageUrl()}
          >
            ${showNewBadge
              ? html`<span class="paper-new-badge" slot="corner">New</span>`
              : nothing}
          </paper-card>
        </a>
      `;
    };
    const renderEmpty = () => {
      return html` <div class="empty-message">No papers available</div> `;
    };

    return html`
      ${items.length === 0 ? renderEmpty() : nothing}
      <div class="preview-gallery">
        ${items.map((item) => renderItem(item))}
      </div>
    `;
  }
}

/** Paper preview card */
@customElement("paper-card")
export class PaperCard extends MobxLitElement {
  static override styles: CSSResultGroup = [styles];

  @property({ type: Object }) metadata: ArxivMetadata | null = null;
  @property({ type: Object }) image: { image_storage_path: string } | null = null;
  @property({ type: Boolean }) disabled = false;
  @property({ type: Number }) summaryMaxCharacters = 250;
  @property({ type: String }) status = "";
  @property({ type: Object }) getImageUrl?: (path: string) => Promise<string>;

  private renderImage() {
    if (
      this.image == null ||
      this.getImageUrl == null ||
      !this.image.image_storage_path
    ) {
      return html`<div class="preview-image preview-image-gradient"></div>`;
    }
    return html`<lumi-image
      class="preview-image"
      .storagePath=${this.image.image_storage_path}
      .getImageUrl=${this.getImageUrl}
    ></lumi-image>`;
  }

  override render() {
    // TODO: Render loading state for paper card if no metadata
    if (!this.metadata) {
      return nothing;
    }

    const classes = { "preview-item": true, disabled: this.disabled };

    // If summary is over max characters, abbreviate
    const summary =
      this.metadata.summary.length <= this.summaryMaxCharacters
        ? this.metadata.summary
        : `${this.metadata.summary.slice(0, this.summaryMaxCharacters)}...`;

    const authors = this.metadata.authors.join(", ");
    return html`
      <div class=${classMap(classes)}>
        <div class="preview-corner">
          <slot name="corner"></slot>
        </div>
        ${this.renderImage()}
        <div class="preview-content">
          <div class="preview-title">${this.metadata.title}</div>
          <div class="preview-metadata">
            <div class="preview-authors" .title=${authors}>${authors}</div>
            <div class="preview-id">(${this.metadata.paperId})</div>
          </div>
          ${this.renderStatusChip()}
          <div class="preview-description">${summary}</div>
        </div>
        <div class="preview-actions">
          <slot name="actions"></slot>
        </div>
      </div>
    `;
  }

  private renderStatusChip() {
    if (!this.status) {
      return nothing;
    }
    return html`<div class="chip secondary">${this.status}</div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "home-gallery": HomeGallery;
    "paper-card": PaperCard;
  }
}
