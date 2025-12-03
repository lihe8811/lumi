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

import { makeObservable, observable, ObservableMap } from "mobx";
import { ArxivCollection } from "../shared/lumi_collection";
import { ArxivMetadata, FeaturedImage } from "../shared/lumi_doc";

import { HistoryService } from "./history.service";
import { Service } from "./service";

interface ServiceProvider {
  historyService: HistoryService;
}

export class HomeService extends Service {
  constructor(private readonly sp: ServiceProvider) {
    super();
    makeObservable(this, {
      hasLoadedCollections: observable,
      isLoadingCollections: observable,
      showUploadDialog: observable,
    });
  }

  hasLoadedCollections = true;
  isLoadingCollections = false;

  // Whether or not to show "upload papers" dialog
  showUploadDialog = false;

  /** Sets visibility for "upload papers" dialog. */
  setShowUploadDialog(showUpload: boolean) {
    this.showUploadDialog = showUpload;
  }

  // Collection-related methods removed (local-only mode).
}
