# Company and route models placeholder
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    areas_served = models.TextField()
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Companies'

class Route(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='routes')
    name = models.CharField(max_length=200)
    start_point = models.CharField(max_length=100)
    end_point = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.company.name} - {self.name}"