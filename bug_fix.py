import lancedb
db = lancedb.connect("agent_carter_lancedb")
tbl = db.open_table("contacts")
row = tbl.head()
print(row)
