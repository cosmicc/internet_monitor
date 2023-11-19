from datetime import datetime
import pytz

# Create a UTC datetime object
utc_datetime = datetime.utcnow().replace(tzinfo=pytz.utc)

# Convert UTC to Eastern Standard Time (EST)
est_timezone = pytz.timezone('US/Eastern')
est_datetime = utc_datetime.astimezone(est_timezone)

print("UTC datetime:", utc_datetime)
print("EST datetime:", est_datetime)

