export const REQUIRED_COLUMNS = [
  "ID",
  "ParentID",
  "File",
  "Content.DescriptionLevel",
  "Content.Title",
  "Content.StartDate",
  "Content.EndDate",
] as const;

export const VALID_DESCRIPTION_LEVELS = [
  "RecordGrp",
  "SubGrp",
  "Series",
  "Subseries",
  "File",
  "Item",
  "OtherLevel",
] as const;

export type DescriptionLevel = (typeof VALID_DESCRIPTION_LEVELS)[number];
