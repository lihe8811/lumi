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

const UNSUPPORTED_KATEX_COMMANDS: RegExp[] = [
  /\\label\{[^}]*\}/g,
  /\\tag\{[^}]*\}/g,
  /\\notag\b/g,
  /\\nonumber\b/g,
];

export function sanitizeLatexForKatex(input: string): string {
  let sanitized = input;
  UNSUPPORTED_KATEX_COMMANDS.forEach((pattern) => {
    sanitized = sanitized.replace(pattern, "");
  });
  return sanitized;
}
