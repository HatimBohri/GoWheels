from django.db import models
from datetime import date, timedelta
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

# ==========================================
# 1. VEHICLE MODELS
# ==========================================

class Vehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('car', 'Car'),
        ('bike', 'Bike'),
    ]

    FUEL_CHOICES = [
        ('Petrol', 'Petrol'),
        ('Diesel', 'Diesel'),
        ('Electric', 'Electric'),
        ('Hybrid', 'Hybrid'),
    ]

    CATEGORY_CHOICES = [
        ('All', 'All'),
        ('Touring', 'Touring'),
        ('Sedan', 'Sedan'),
        ('Hatchback', 'Hatchback'),
        ('SUV', 'SUV'),
        ('Dual-Sport', 'Dual-Sport'),
        ('Crossover (CUV)', 'Crossover (CUV)'),
        ('Off-Road 1 Dirt Bike', 'Off-Road 1 Dirt Bike'),
        ('Coupe', 'Coupe'),
        ('Scooter', 'Scooter'),
        ('MPV/Minivan', 'MPV/Minivan'),
        ('Moped', 'Moped'),
        ('Convertible', 'Convertible'),
        ('Pickup Truck', 'Pickup Truck'),
        ('Standard (Naked)', 'Standard (Naked)'),
        ('Sportbike', 'Sportbike'),
        ('Cruiser', 'Cruiser'),
        ('Adventure (ADV)', 'Adventure (ADV)'),
        ('Electric Motorcycle', 'Electric Motorcycle'),
    ]

    SEATS_CHOICES = [
        (2, '2'),
        (4, '4'),
        (8, '8'),
        (12, '12+'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vehicles")
    contact_number = models.CharField(max_length=15)
    vehicle_name = models.CharField(max_length=100)
    vehicle_type = models.CharField(max_length=10, choices=VEHICLE_TYPE_CHOICES)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    price_per_day = models.IntegerField()
    seats = models.IntegerField(choices=SEATS_CHOICES, null=True, blank=True)
    fuel_type = models.CharField(max_length=30, choices=FUEL_CHOICES)
    pickup_location = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    available = models.BooleanField(default=True)

    def __str__(self):
        return self.vehicle_name

    def is_booked(self):
        today = date.today()
        return Rental.objects.filter(
            vehicle=self,
            start_date__lte=today,
            end_date__gte=today
        ).exists()

    def next_available_date(self):
        today = date.today()
        active_rental = (
            Rental.objects
            .filter(vehicle=self, end_date__gte=today)
            .order_by('end_date')
            .first()
        )
        if active_rental:
            return active_rental.end_date + timedelta(days=1)
        return today

class VehicleImage(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to='vehicles/')
    image_type = models.CharField(
        max_length=10,
        choices=[('front','Front'), ('back','Back'), ('inside','Inside'), ('other','Other')]    
    )

    def __str__(self):
        return f"{self.vehicle.vehicle_name} - {self.image_type}"


# ==========================================
# 2. DRIVER MODELS
# ==========================================

class DriverApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100)
    age = models.IntegerField()
    phone_number = models.CharField(max_length=15)
    experience_years = models.IntegerField()
    rating = models.FloatField(default=5.0)
    price_per_day = models.IntegerField()
    aadhaar_image = models.ImageField(upload_to='driver_docs/aadhaar/')
    license_image = models.ImageField(upload_to='driver_docs/license/')
    profile_photo = models.ImageField(upload_to='driver_docs/profile/')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.user.username})"

    def save(self, *args, **kwargs):
        # 1. Save the application first
        super().save(*args, **kwargs)
        
        # 2. Check if it was just approved AND doesn't have a linked driver yet
        if self.status == 'approved' and not hasattr(self, 'driver'):
            # Import Driver HERE to avoid Circular Dependency/NameError
            from .models import Driver 
            
            # Automatically spawn the linked Driver profile!
            Driver.objects.create(
                application=self,
                name=self.full_name,
                age=self.age,
                phone_number=self.phone_number,
                experience_years=self.experience_years,
                rating=5.0,
                price_per_day=self.price_per_day,
                aadhaar_image=self.aadhaar_image,
                license_image=self.license_image,
                photo=self.profile_photo,
                available=True
            )

class Driver(models.Model):
    application = models.OneToOneField(
        DriverApplication,
        on_delete=models.CASCADE,
        related_name="driver",
        null=True,
        blank=True
    )
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    phone_number = models.CharField(max_length=15)
    experience_years = models.IntegerField()
    rating = models.FloatField(default=5.0)
    price_per_day = models.IntegerField()
    aadhaar_image = models.ImageField(upload_to='driver_docs/aadhaar/', null=True, blank=True)
    license_image = models.ImageField(upload_to='driver_docs/license/', null=True, blank=True)
    photo = models.ImageField(upload_to='drivers/', null=True, blank=True)
    available = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# ==========================================
# 3. RENTAL MODEL
# ==========================================

class Rental(models.Model):
    DRIVE_TYPE_CHOICES = [
        ('self', 'Self-Driving'),
        ('driver', 'With GoWheels Driver'),
    ]
    
    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash on Pickup'),
        ('online', 'Online Payment'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="rental")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True)
    
    start_date = models.DateField()
    end_date = models.DateField()
    total_price = models.IntegerField()
    
    full_name = models.CharField(max_length=150)
    age = models.IntegerField()
    phone_number = models.CharField(max_length=15)
    aadhaar_image = models.ImageField(upload_to='documents/aadhaar/')
    license_image = models.ImageField(upload_to='documents/license/')
    
    drive_type = models.CharField(max_length=10, choices=DRIVE_TYPE_CHOICES, default='self')
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODE_CHOICES, default='cash')
    
    rented_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} -> {self.vehicle.vehicle_name} ({self.payment_mode})"


# ==========================================
# 4. WALLET SYSTEM
# ==========================================

class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - ₹{self.balance}"

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('CREDIT', 'Credit'), # Adding money
        ('DEBIT', 'Debit'),   # Paying for rental
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default='SUCCESS')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type} - ₹{self.amount}"

# Signals to Auto-Create Wallet
@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_wallet(sender, instance, **kwargs):
    # Check if wallet exists before saving to avoid errors
    if hasattr(instance, 'wallet'):
        instance.wallet.save()