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

import "../../pair-components/button";
import "../../pair-components/textinput";
import "../gallery/home_gallery";

import { MobxLitElement } from "@adobe/lit-mobx";
import { CSSResultGroup, html, nothing } from "lit";
import { customElement, state } from "lit/decorators.js";

import { core } from "../../core/core";
import { BackendApiService } from "../../services/backend_api.service";
import { getArxivPaperUrl } from "../../services/router.service";
import { SettingsService } from "../../services/settings.service";
import { ArxivMetadata } from "../../shared/lumi_doc";
import { styles } from "./arxiv_discover.scss";

type DiscoverMode = "recent" | "search";

@customElement("arxiv-discover")
export class ArxivDiscover extends MobxLitElement {
  static override styles: CSSResultGroup = [styles];

  private readonly backendApiService = core.getService(BackendApiService);
  private readonly settingsService = core.getService(SettingsService);
  private readonly pageSize = 25;

  @state() private searchQuery = "";
  @state() private mode: DiscoverMode = "recent";
  @state() private isLoading = false;
  @state() private errorMessage = "";
  @state() private papers: ArxivMetadata[] = [];
  @state() private total = 0;
  @state() private page = 1;

  override firstUpdated() {
    this.loadRecent(true);
  }

  private async loadRecent(reset = true) {
    this.mode = "recent";
    await this.fetchResults(reset);
  }

  private async runSearch(reset = true) {
    if (!this.searchQuery.trim()) {
      await this.loadRecent(reset);
      return;
    }
    this.mode = "search";
    await this.fetchResults(reset);
  }

  private async fetchResults(reset: boolean) {
    if (this.isLoading) return;
    this.isLoading = true;
    this.errorMessage = "";
    const nextPage = reset ? 1 : this.page + 1;
    try {
      const categories = this.settingsService.discoverCategories.value;
      const resp =
        this.mode === "search"
          ? await this.backendApiService.searchArxivPapers(
              this.searchQuery,
              nextPage,
              this.pageSize,
              categories
            )
          : await this.backendApiService.listArxivRecent(
              nextPage,
              this.pageSize,
              categories
            );
      const items = resp.papers.map((paper) => paper.metadata);
      this.papers = reset ? items : [...this.papers, ...items];
      this.total = resp.total;
      this.page = resp.page;
    } catch (error) {
      this.errorMessage = (error as Error).message;
    } finally {
      this.isLoading = false;
    }
  }

  private get hasMore() {
    return this.papers.length < this.total;
  }

  private renderSearchPanel() {
    return html`
      <div class="search-panel">
        <div class="search-bar">
          <pr-textinput
            size="medium"
            class="search-input"
            .value=${this.searchQuery}
            .onChange=${(e: InputEvent) => {
              this.searchQuery = (e.target as HTMLInputElement).value;
            }}
            .onKeydown=${(e: KeyboardEvent) => {
              if (e.key === "Enter") {
                this.runSearch(true);
              }
            }}
            placeholder="Search titles, authors, or abstracts"
          ></pr-textinput>
          <div class="search-actions">
            <pr-button
              variant="filled"
              ?disabled=${this.isLoading}
              @click=${() => this.runSearch(true)}
              >Search</pr-button
            >
            <pr-button
              variant="outlined"
              ?disabled=${this.isLoading}
              @click=${() => {
                this.searchQuery = "";
                this.loadRecent(true);
              }}
              >Latest</pr-button
            >
          </div>
        </div>
        ${this.errorMessage
          ? html`<div class="error-message">${this.errorMessage}</div>`
          : nothing}
      </div>
    `;
  }

  private formatPublishedDate(value: string) {
    if (!value) {
      return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return parsed.toISOString().slice(0, 10);
  }

  private formatCategoryBadge(categories?: string[]) {
    if (!categories || categories.length === 0) {
      return "";
    }
    if (categories.length === 1) {
      return categories[0];
    }
    return `${categories[0]} +${categories.length - 1}`;
  }

  private getCoverImagePath(categories?: string[]) {
    const available = new Set(["cs.AI", "cs.CL", "cs.CV", "cs.MA", "cs.RO"]);
    if (categories) {
      for (const category of categories) {
        if (available.has(category)) {
          return `assets/${category}.png`;
        }
      }
    }
    return "assets/cs.AI.png";
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

  private renderResults() {
    if (this.isLoading && this.papers.length === 0) {
      return html`<div class="loading-message">Loading papers...</div>`;
    }

    if (this.papers.length === 0 && !this.isLoading) {
      return html`<div class="empty-message">No papers found.</div>`;
    }

    return html`
      <div class="preview-gallery">
        ${this.papers.map(
          (paper) => html`
            <div class="result-card">
              <paper-card
                .metadata=${paper}
                .image=${{
                  image_storage_path: this.getCoverImagePath(paper.categories),
                }}
                .getImageUrl=${this.getImageUrl()}
                style="--paper-card-line-clamp: 4;"
              >
                <span class="paper-date-badge" slot="corner">
                  ${this.formatPublishedDate(paper.publishedTimestamp)}
                </span>
                ${this.formatCategoryBadge(paper.categories)
                  ? html`<span class="paper-category-badge" slot="corner">
                      ${this.formatCategoryBadge(paper.categories)}
                    </span>`
                  : nothing}
                <pr-button
                  class="cta-pill"
                  variant="tonal"
                  slot="actions"
                  @click=${() =>
                    window.open(getArxivPaperUrl(paper.paperId), "_blank")}
                  >Open on arXiv</pr-button
                >
                <pr-button class="cta-pill" variant="tonal" slot="actions" disabled
                  >Add to Lumi (soon)</pr-button
                >
              </paper-card>
            </div>
          `
        )}
      </div>
    `;
  }

  private renderFooter() {
    if (!this.hasMore || this.isLoading) {
      return nothing;
    }
    return html`
      <div class="footer">
        <pr-button variant="outlined" @click=${() => this.fetchResults(false)}
          >Load more</pr-button
        >
      </div>
    `;
  }

  override render() {
    return html`
      ${this.renderSearchPanel()}
      ${this.renderResults()}
      ${this.renderFooter()}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "arxiv-discover": ArxivDiscover;
  }
}
