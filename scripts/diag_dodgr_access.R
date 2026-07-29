library(sf)
library(data.table)
library(dodgr)

repo <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"

tracts <- st_read(file.path(repo, "static/data/tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tracts <- st_transform(tracts, 4326)
tract_pts <- st_point_on_surface(tracts)

shelters <- st_read(file.path(repo, "static/data/nss_lake_county_facilities.geojson"), quiet = TRUE)
shelters <- st_transform(shelters, 4326)

bbox <- st_bbox(tracts)
street <- dodgr_streetnet(bbox = bbox, expand = 0.10, quiet = FALSE)
cat("street rows:", nrow(street), "\n")

graph <- weight_streetnet(street, wt_profile = "motorcar")
cat("graph rows:", nrow(graph), "\n")

orig_xy <- st_coordinates(tract_pts)
dest_xy <- st_coordinates(shelters)

orig_match <- match_pts_to_graph(graph, orig_xy)
dest_match <- match_pts_to_graph(graph, dest_xy)

orig_ids <- graph$from_id[orig_match]
dest_ids <- graph$from_id[dest_match]

# small sample test first
from_sample <- unique(orig_ids)[1:3]
to_sample <- unique(dest_ids)[1:5]

tm_small <- dodgr_times(graph, from = from_sample, to = to_sample)
cat("small dim:", nrow(tm_small), ncol(tm_small), "\n")
print(tm_small)

# full matrix
tm <- dodgr_times(graph, from = orig_ids, to = dest_ids)
cat("full dim:", nrow(tm), ncol(tm), "\n")
cat("global min:", min(tm, na.rm = TRUE), "global max:", max(tm, na.rm = TRUE), "\n")

mins <- apply(tm, 1, min, na.rm = TRUE)
maxs <- apply(tm, 1, max, na.rm = TRUE)
cat("origin-min range:", min(mins), max(mins), "\n")
cat("origin-max range:", min(maxs), max(maxs), "\n")

# Assume dodgr_times returns seconds and test 30 min threshold.
counts30 <- rowSums(is.finite(tm) & tm <= 1800, na.rm = TRUE)
cat("count<=30min range:", min(counts30), max(counts30), "\n")
print(data.frame(GEOID = as.character(tract_pts$GEOID), count_30 = counts30))
