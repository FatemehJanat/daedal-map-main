library(sf)
library(data.table)
library(osrm)

repo <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"
tr <- st_read(file.path(repo, "static/data/tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tr <- st_transform(tr, 4326)
trp <- st_point_on_surface(tr)
sh <- st_read(file.path(repo, "static/data/nss_lake_county_facilities.geojson"), quiet = TRUE)
sh <- st_transform(sh, 4326)

src <- data.frame(id = "o1", lon = st_coordinates(trp)[1, 1], lat = st_coordinates(trp)[1, 2])
dst <- data.frame(id = paste0("d", seq_len(nrow(sh))), lon = st_coordinates(sh)[, 1], lat = st_coordinates(sh)[, 2])

options(osrm.server = "https://router.project-osrm.org/", osrm.profile = "car")
res <- osrmTable(
  src = st_as_sf(src, coords = c("lon", "lat"), crs = 4326, remove = FALSE),
  dst = st_as_sf(dst, coords = c("lon", "lat"), crs = 4326, remove = FALSE)
)

m <- as.matrix(res$durations)
cat("dim", nrow(m), ncol(m), "\n")
cat("min", min(m, na.rm = TRUE), "max", max(m, na.rm = TRUE), "\n")
print(m[1, 1:min(10, ncol(m))])
