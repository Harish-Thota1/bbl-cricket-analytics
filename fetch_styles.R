library(cricketdata)

ids  <- eval(parse(text = readLines("cricinfo_ids.txt")))
cat("fetching", length(ids), "players\n")

meta <- fetch_player_meta(ids)
write.csv(meta, "bowler_meta_all.csv", row.names = FALSE)
cat(nrow(meta), "written to bowler_meta_all.csv\n")
