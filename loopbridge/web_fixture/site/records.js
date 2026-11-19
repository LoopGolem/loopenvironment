// SPDX-License-Identifier: Apache-2.0
const query = new URLSearchParams(location.search);
const name = (query.get("query") || "").toLowerCase();
const region = query.get("region");
const records = [
  ["R-101", "Harbor sensor", "north", "12"],
  ["R-102", "Harbor relay", "south", "4"],
  ["R-103", "Orchard sensor", "north", "7"],
  ["R-104", "Harbor gateway", "north", "9"],
];
for (const record of records) {
  if (!record[1].toLowerCase().includes(name) || (region !== "all" && record[2] !== region)) {
    continue;
  }
  const row = document.createElement("tr");
  for (const value of record) {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.append(cell);
  }
  document.querySelector("#rows").append(row);
}
document.documentElement.dataset.resultsReady = "true";
