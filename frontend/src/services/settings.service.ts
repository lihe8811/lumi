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

import { action, computed, makeObservable, observable } from "mobx";
import { Service } from "./service";

import { ColorMode } from "../shared/types";

import {
  LocalStorageHelper,
  LocalStorageService,
} from "./local_storage.service";

interface ServiceProvider {
  localStorageService: LocalStorageService;
}

const TOS_CONFIRMED_LOCAL_STORAGE_KEY = "tosConfirmed";
const TUTORIAL_CONFIRMED_LOCAL_STORAGE_KEY = "tutorialConfirmed";
const DISCOVER_CATEGORIES_LOCAL_STORAGE_KEY = "discoverCategories";
const DEFAULT_DISCOVER_CATEGORIES = [
  "cs.CV",
  "cs.LG",
  "cs.CL",
  "cs.AI",
  "cs.NE",
  "cs.RO",
  "cs.MA",
];

/**
 * Settings service.
 */
export class SettingsService extends Service {
  constructor(private readonly sp: ServiceProvider) {
    super();
    makeObservable(this);

    this.isTosConfirmed = this.sp.localStorageService.makeLocalStorageHelper(
      TOS_CONFIRMED_LOCAL_STORAGE_KEY,
      false
    );
    this.isTutorialConfirmed =
      this.sp.localStorageService.makeLocalStorageHelper(
        TUTORIAL_CONFIRMED_LOCAL_STORAGE_KEY,
        false
      );
    this.discoverCategories = this.sp.localStorageService.makeLocalStorageHelper(
      DISCOVER_CATEGORIES_LOCAL_STORAGE_KEY,
      DEFAULT_DISCOVER_CATEGORIES
    );
    this.discoverCategoriesDraft = this.discoverCategories.value.join(", ");
  }

  @observable colorMode: ColorMode = ColorMode.DEFAULT;

  readonly isTosConfirmed: LocalStorageHelper<boolean>;
  readonly isTutorialConfirmed: LocalStorageHelper<boolean>;
  readonly discoverCategories: LocalStorageHelper<string[]>;
  @observable discoverCategoriesDraft = "";

  @action setColorMode(colorMode: ColorMode) {
    this.colorMode = colorMode;
  }

  @computed
  get isDiscoverCategoriesDirty() {
    return (
      this.discoverCategoriesDraft.trim() !==
      this.discoverCategories.value.join(", ")
    );
  }

  @action
  setDiscoverCategoriesDraft(value: string) {
    this.discoverCategoriesDraft = value;
  }

  @action
  saveDiscoverCategories() {
    const categories = this.discoverCategoriesDraft
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
    this.discoverCategories.value = categories;
    this.discoverCategoriesDraft = categories.join(", ");
  }
}
