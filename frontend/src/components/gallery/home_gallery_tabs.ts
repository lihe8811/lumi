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

import "../../pair-components/icon";

import { MobxLitElement } from "@adobe/lit-mobx";
import { CSSResultGroup, html } from "lit";
import { customElement } from "lit/decorators.js";
import { classMap } from "lit/directives/class-map.js";

import { core } from "../../core/core";
import { Pages, RouterService } from "../../services/router.service";
import { styles } from "./home_gallery_tabs.scss";

/** Tabs for home/discover gallery pages. */
@customElement("home-gallery-tabs")
export class HomeGalleryTabs extends MobxLitElement {
  static override styles: CSSResultGroup = [styles];

  private readonly routerService = core.getService(RouterService);

  override render() {
    return html`<div class="tabs-menu">
      ${this.renderTab(
        Pages.HOME,
        "My collection",
        "bookmarks"
      )}${this.renderTab(
        Pages.DISCOVER,
        "Discover",
        "newsstand"
      )}
    </div>`;
  }

  private renderTab(page: Pages, label: string, icon: string) {
    const classes = classMap({
      "tab-item": true,
      active: this.routerService.activePage === page,
    });

    const navigate = () => {
      this.routerService.navigate(page);
    };

    return html`
      <div class=${classes} role="button" @click=${navigate}>
        <pr-icon icon=${icon} size="small"></pr-icon>
        <span>${label}</span>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "home-gallery-tabs": HomeGalleryTabs;
  }
}
