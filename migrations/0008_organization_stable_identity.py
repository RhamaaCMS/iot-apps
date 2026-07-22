from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("iot", "0007_mqtt_outbox")]

    operations = [
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                Lower("name"), name="iot_organization_name_ci_uniq"
            ),
        )
    ]
