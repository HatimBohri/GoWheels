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
        ('truck', 'Truck'),
    ]

    FUEL_CHOICES = [
        ('Petrol', 'Petrol'),
        ('Diesel', 'Diesel'),
        ('Electric', 'Electric'),
        ('Hybrid', 'Hybrid'),
        ('CNG', 'CNG'),  
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
            ('Minibus', 'Minibus'),
        ]

    SEATS_CHOICES = [
        (2, '2'),
        (4, '4'),
        (5, '5'),  
        (7, '7'),  
        (8, '8'),
        (12, '12+'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vehicles")
    contact_number = models.CharField(max_length=15)
    vehicle_name = models.CharField(max_length=100)
    vehicle_number = models.CharField(max_length=20, blank=True, null=True)
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

    # ==========================================
    # NEW RATING PROPERTIES (ADDED HERE)
    # ==========================================
    @property
    def avg_rating(self):
        reviews = self.reviews.all()
        if not reviews.exists():
            return 0.0  # Returns 0 if there are no reviews yet
        total = sum(r.vehicle_avg for r in reviews)
        return round(total / reviews.count(), 1)

    @property
    def review_count(self):
        return self.reviews.count()

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

# ==========================================
# 2. DRIVER MODELS
# ==========================================

class Driver(models.Model):
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

    def update_rating(self):
        reviews = self.reviews.exclude(driver_rating__isnull=True)
        if reviews.exists():
            total = sum(r.driver_rating for r in reviews)
            self.rating = round(total / reviews.count(), 1)
            self.save()

    @property
    def is_booked_today(self):
        from django.utils import timezone
        today = timezone.now().date()
        # Checks if driver has any active trips today
        return self.rental_set.filter(
            start_date__lte=today, 
            end_date__gte=today
        ).exclude(status__in=['CANCELLED', 'COMPLETED']).exists()

    def is_available_for_dates(self, start_date, end_date):
        # Checks if driver is free for the requested date range
        return not self.rental_set.filter(
            start_date__lte=end_date, 
            end_date__gte=start_date
        ).exclude(status__in=['CANCELLED', 'COMPLETED']).exists()

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
        ('upi', 'UPI Payment'),
        ('wallet', 'Wallet Payment'),
    ]

    # --- ADD THESE CHOICES ---
    STATUS_CHOICES = [
        ('ACTIVE', 'Active/Ongoing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="rental")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True)
    
    start_date = models.DateField()
    end_date = models.DateField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    full_name = models.CharField(max_length=150)
    age = models.IntegerField()
    phone_number = models.CharField(max_length=15)
    aadhaar_image = models.ImageField(upload_to='documents/aadhaar/')
    license_image = models.ImageField(upload_to='documents/license/')

    special_notes = models.TextField(blank=True, null=True)
    promo_code = models.CharField(max_length=20, blank=True, null=True)
    
    drive_type = models.CharField(max_length=10, choices=DRIVE_TYPE_CHOICES, default='self')
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='cash')
    
    rented_at = models.DateTimeField(auto_now_add=True)

    # ==========================================
    # --- ADD THESE 4 NEW FIELDS ---
    # ==========================================
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    actual_return_date = models.DateField(null=True, blank=True)
    security_deposit_held = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    penalty_applied = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.user.username} -> {self.vehicle.vehicle_name} ({self.status})"
    
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

# ==========================================
# 5. USER PROFILE (For Phone Numbers)
# ==========================================

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=15, null=True, blank=True)

    cash_on_pickup_blocked = models.BooleanField(default=False, help_text="Blocked from using Cash payment due to past cancellation/no-show.")

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def __str__(self):
        return f"{self.user.username}'s Profile"

# Signals to Auto-Create Profile
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


# ==========================================
# 6. REVIEWS
# ==========================================
class Review(models.Model):
    rental = models.OneToOneField(Rental, on_delete=models.CASCADE, related_name="review")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="reviews")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="reviews", null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    cleanliness = models.IntegerField(default=5)
    performance = models.IntegerField(default=5)
    comfort = models.IntegerField(default=5)
    driver_rating = models.IntegerField(null=True, blank=True) # Optional if no driver selected
    comment = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def vehicle_avg(self):
        """Calculates the average rating for the vehicle specifically"""
        return round((self.cleanliness + self.performance + self.comfort) / 3.0, 1)
    
    # Signal to automatically block cash payments if a rental is cancelled
@receiver(post_save, sender=Rental)
def block_cash_on_cancellation(sender, instance, **kwargs):
    # Assuming you added the 'status' field to Rental from our previous step
    if instance.status == 'CANCELLED':
        profile = instance.user.profile
        profile.cash_on_pickup_blocked = True
        profile.save()