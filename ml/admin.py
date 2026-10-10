from django.contrib import admin

from .models import AnomalyFlag, CustomerSegment, DemandForecast, ModelVersion, ProductAssociation, SalesForecast

for m in (ModelVersion, DemandForecast, SalesForecast, CustomerSegment, AnomalyFlag, ProductAssociation):
    admin.site.register(m)
