import io
import json
import random
import string
from datetime import date, datetime, timedelta

import stripe
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Prefetch, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

# Import all models correctly
from .models import Driver, DriverApplication, Rental, Vehicle, VehicleImage, Wallet, WalletTransaction

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


# ==========================================
# GENERAL PAGES
# ==========================================

def home(request):
    return render(request, 'home.html')

def helpdesk(request):
    return render(request, 'helpdesk.html')

def offers(request):
    return render(request, 'offers.html')


# ==========================================
# CAPTCHA
# ==========================================

def generate_captcha_text(length=5):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choice(chars) for _ in range(length))

def captcha_image(request):
    captcha_text = generate_captcha_text()
    request.session['captcha_code'] = captcha_text

    width, height = 160, 60
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Load font (use a TTF font)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 36)

    # Draw noise dots
    for _ in range(1200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(0, 0, 255))

    # Draw text with slight randomness
    for i, char in enumerate(captcha_text):
        x = 15 + i * 28 + random.randint(-3, 3)
        y = random.randint(5, 15)
        draw.text((x, y), char, font=font, fill=(0, 0, 0))

    # Apply blur
    image = image.filter(ImageFilter.GaussianBlur(0.6))

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)

    return HttpResponse(buffer, content_type="image/png")


# ==========================================
# AUTHENTICATION
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')  # Already logged in

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, f"Welcome back, {username}!")
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password!")

    return render(request, 'login.html')

def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, "signup.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return render(request, "signup.html")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered!")
            return render(request, "signup.html")

        user = User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, "Account created successfully! You can now log in.")
        return redirect("login")

    return render(request, "signup.html")


# ==========================================
# VEHICLES & SEARCH
# ==========================================

@login_required(login_url='login')
def list_vehicle(request):
    if request.method == "POST":
        vehicle = Vehicle.objects.create(
            owner=request.user,  # Assuming owner is tied to user model now
            contact_number=request.POST['contact_number'],
            vehicle_name=request.POST['vehicle_name'],
            vehicle_type=request.POST['vehicle_type'],
            category=request.POST['category'],
            price_per_day=request.POST['price_per_day'],
            seats=request.POST.get('seats') or None,
            fuel_type=request.POST['fuel_type'],
            pickup_location=request.POST['pickup_location'],
        )

        # Save images
        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_front'], image_type='front')
        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_back'], image_type='back')
        VehicleImage.objects.create(vehicle=vehicle, image=request.FILES['image_inside'], image_type='inside')

        additional_images = request.FILES.getlist('additional_images')
        for img in additional_images:
            VehicleImage.objects.create(vehicle=vehicle, image=img, image_type='other')

        return redirect('vehicles')

    return render(request, 'list_vehicle.html')

def vehicles(request):
    qs = Vehicle.objects.all()

    # ===== READ FILTER PARAMS (Empty Strings Filtered) =====
    selected_categories = [c for c in request.GET.getlist('category') if c]
    selected_vehicle_types = [vt for vt in request.GET.getlist('vehicle_type') if vt]
    selected_fuels = [f for f in request.GET.getlist('fuel_type') if f]
    status_filters = [s for s in request.GET.getlist('status') if s]

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    sort = request.GET.get('sort')
    seats = request.GET.get('seats')

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    # ===== PRICE FILTER =====
    if min_price:
        qs = qs.filter(price_per_day__gte=min_price)
    if max_price:
        qs = qs.filter(price_per_day__lte=max_price)

    # ===== DATE AVAILABILITY FILTER (Crash Handled) =====
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

            if start <= end:
                booked_ids = Rental.objects.filter(
                    start_date__lte=end,
                    end_date__gte=start
                ).values_list("vehicle_id", flat=True)

                qs = qs.exclude(id__in=booked_ids)
            else:
                messages.error(request, "Start date cannot be after End date.")
        except ValueError:
            pass

    # ===== CATEGORY / TYPE / FUEL =====
    if selected_categories:
        qs = qs.filter(category__in=selected_categories)

    if selected_vehicle_types:
        qs = qs.filter(vehicle_type__in=selected_vehicle_types)

    if selected_fuels:
        qs = qs.filter(fuel_type__in=selected_fuels)

    # ===== SEATS FILTER =====
    if seats:
        qs = qs.filter(seats__gte=int(seats))

    # ===== STATUS FILTER =====
    today = date.today()

    if status_filters:
        if "available" in status_filters and "soon" not in status_filters:
            qs = qs.exclude(
                rental__start_date__lte=today,
                rental__end_date__gte=today
            )

        elif "soon" in status_filters and "available" not in status_filters:
            qs = qs.filter(
                rental__start_date__lte=today,
                rental__end_date__gte=today
            ).distinct()

    # ===== SORTING =====
    if sort == "price_low":
        qs = qs.order_by("price_per_day")
    elif sort == "price_high":
        qs = qs.order_by("-price_per_day")
    else:
        qs = qs.order_by("-created_at")

    # ===== ATTACH IMAGE & STATUS =====
    for v in qs:
        v.front_image = v.images.filter(image_type="front").first()
        v.is_booked_today = v.is_booked()
        if v.is_booked_today:
            v.available_from = v.next_available_date()

    return render(request, "vehicles.html", {
        "vehicles": qs,
        "categories": Vehicle.CATEGORY_CHOICES,
        "fuel_choices": Vehicle.FUEL_CHOICES,
        "selected_categories": selected_categories,
        "selected_vehicle_types": selected_vehicle_types,
        "selected_fuels": selected_fuels,
        "request": request,
    })

@login_required
def your_vehicles(request):
    # Get only vehicles added by the logged-in user
    vehicles = Vehicle.objects.filter(owner=request.user).order_by('-created_at')

    # Attach front images and booked status
    for v in vehicles:
        v.front_image = v.images.filter(image_type="front").first()
        v.is_booked_today = v.is_booked()

    return render(request, "your_vehicles.html", {"vehicles": vehicles})


# ==========================================
# RENTALS & BOOKINGS
# ==========================================

def vehicle_booked_dates(request, vehicle_id):
    bookings = Rental.objects.filter(
        vehicle_id=vehicle_id
    ).values('start_date', 'end_date')
    return JsonResponse(list(bookings), safe=False)

def is_vehicle_available(vehicle, start_date, end_date):
    return not Rental.objects.filter(
        vehicle=vehicle,
        start_date__lte=end_date,
        end_date__gte=start_date
    ).exists()

@login_required
def rent_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)
    driver_applications = DriverApplication.objects.filter(status="approved")
    
    # GET USER WALLET (For balance check)
    user_wallet, _ = Wallet.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # --- CAPTCHA VALIDATION ---
        captcha_input = request.POST.get("captcha_input", "").upper()
        captcha_code = request.session.get("captcha_code")
        if not captcha_code or captcha_input != captcha_code:
            messages.error(request, "Invalid captcha.")
            return redirect(request.path)
        del request.session['captcha_code']

        # --- GET FORM DATA ---
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        drive_type = request.POST.get("drive_type") or "self"
        driver_id = request.POST.get("driver_id")
        payment_mode = request.POST.get("payment_mode") # 'online', 'cash', or 'wallet'
        
        full_name = request.POST.get("full_name")
        age = request.POST.get("age")
        phone_number = request.POST.get("phone_number")
        aadhaar_image = request.FILES.get("aadhaar_image")
        license_image = request.FILES.get("license_image")

        # --- CALCULATIONS ---
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Invalid dates.")
            return redirect(request.path)
        
        if not is_vehicle_available(vehicle, start, end):
            messages.error(request, "Vehicle unavailable for these dates.")
            return redirect(request.path)

        days = (end - start).days + 1
        total_price = days * vehicle.price_per_day
        selected_driver = None

        if drive_type == "driver" and driver_id:
            selected_driver = Driver.objects.get(id=int(driver_id))
            total_price += days * selected_driver.price_per_day

        # ==========================================
        # PAYMENT LOGIC
        # ==========================================

        # --- OPTION A: WALLET PAYMENT ---
        if payment_mode == 'wallet':
            if user_wallet.balance >= total_price:
                user_wallet.balance -= total_price
                user_wallet.save()
                
                WalletTransaction.objects.create(
                    wallet=user_wallet,
                    amount=total_price,
                    transaction_type='DEBIT',
                    description=f"Rental: {vehicle.vehicle_name}",
                    status='SUCCESS'
                )
                
                Rental.objects.create(
                    user=request.user,
                    vehicle=vehicle,
                    driver=selected_driver,
                    start_date=start,
                    end_date=end,
                    total_price=total_price,
                    full_name=full_name,
                    age=age,
                    phone_number=phone_number,
                    drive_type=drive_type,
                    payment_mode='wallet',
                    aadhaar_image=aadhaar_image,
                    license_image=license_image
                )
                messages.success(request, f"Booking Successful! ₹{total_price} paid via Wallet.")
                return redirect("rent_history")
            else:
                messages.error(request, f"Insufficient Wallet Balance (Required: ₹{total_price})")
                return redirect(request.path)

        # --- OPTION B: ONLINE (STRIPE) ---
        elif payment_mode == 'online':
            request.session['booking_data'] = {
                'vehicle_id': vehicle.id,
                'start_date': start_date,
                'end_date': end_date,
                'total_price': float(total_price),
                'full_name': full_name,
                'age': age,
                'phone_number': phone_number,
                'drive_type': drive_type,
                'driver_id': driver_id,
                'payment_mode': 'online'
            }
            
            domain_url = 'http://127.0.0.1:8000/'
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'inr',
                        'product_data': {'name': f"Rent {vehicle.vehicle_name}"},
                        'unit_amount': int(total_price * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=domain_url + 'rent/success/',
                cancel_url=domain_url + f'rent/{vehicle.id}/',
            )
            return redirect(checkout_session.url, code=303)

        # --- OPTION C: CASH ON PICKUP ---
        else:
            Rental.objects.create(
                user=request.user,
                vehicle=vehicle,
                driver=selected_driver,
                start_date=start,
                end_date=end,
                total_price=total_price,
                full_name=full_name,
                age=age,
                phone_number=phone_number,
                drive_type=drive_type,
                payment_mode='cash',
                aadhaar_image=aadhaar_image,
                license_image=license_image
            )
            messages.success(request, "Booking Confirmed! Please pay cash on pickup.")
            return redirect("rent_history")

    return render(request, "rent_vehicle.html", {
        "vehicle": vehicle,
        "driver_applications": driver_applications,
        "wallet_balance": user_wallet.balance,
    })

def finalize_booking(request):
    data = request.session.get('booking_data')
    if not data:
        return redirect('home')

    vehicle = Vehicle.objects.get(id=data['vehicle_id'])
    
    selected_driver = None
    if data['driver_id']:
        selected_driver = Driver.objects.get(id=int(data['driver_id']))

    Rental.objects.create(
        user=request.user,
        vehicle=vehicle,
        driver=selected_driver,
        start_date=data['start_date'],
        end_date=data['end_date'],
        total_price=data['total_price'],
        full_name=data['full_name'],
        age=data['age'],
        phone_number=data['phone_number'],
        drive_type=data['drive_type'],
        payment_mode=data['payment_mode'],
    )

    del request.session['booking_data']
    messages.success(request, "Booking Confirmed Successfully!")
    return redirect("rent_history")

@login_required
def rent_success_callback(request):
    """ Stripe redirects here after payment. We finalize the booking. """
    return finalize_booking(request)


# ==========================================
# DASHBOARD / USER GRAPHICS
# ==========================================

@login_required
def auto_fix_graph(request):
    user = request.user
    
    vehicle = Vehicle.objects.first()
    if not vehicle:
        vehicle = Vehicle.objects.create(
            owner=user, 
            vehicle_name="Test Graph Car", 
            contact_number="0000000000",
            vehicle_type="car",
            category="Sedan",
            price_per_day=1000,
            fuel_type="Petrol",
            pickup_location="Test City"
        )

    dates = [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 20),
        date(2026, 1, 28),
        date(2026, 2, 5),
    ]

    existing_rentals = list(Rental.objects.filter(user=user))
    
    for i, start_dt in enumerate(dates):
        end_dt = start_dt + timedelta(days=2)
        price = 2000
        
        if i < len(existing_rentals):
            rental = existing_rentals[i]
            rental.start_date = start_dt
            rental.end_date = end_dt
            rental.total_price = price
            rental.save()
        else:
            ref_rental = existing_rentals[0] if existing_rentals else None
            Rental.objects.create(
                user=user,
                vehicle=vehicle,
                start_date=start_dt,
                end_date=end_dt,
                total_price=price,
                full_name=user.get_full_name() or user.username,
                age=25,
                phone_number="9999999999",
                drive_type="self",
                payment_mode="online",
                aadhaar_image=ref_rental.aadhaar_image if ref_rental else "defaults/doc.jpg",
                license_image=ref_rental.license_image if ref_rental else "defaults/doc.jpg"
            )

    messages.success(request, "Graph Data Fixed! Added 5 weekly data points.")
    return redirect('rent_history')

@login_required
def rent_history(request):
    today = timezone.now().date()

    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'all')
    sort_by = request.GET.get('sort', '-rented_at')

    allowed_sorts = ['rented_at', '-rented_at', 'total_price', '-total_price']
    if sort_by not in allowed_sorts:
        sort_by = '-rented_at'

    rentals_qs = Rental.objects.filter(user=request.user) \
        .select_related('vehicle') \
        .prefetch_related(
            Prefetch(
                'vehicle__images',
                queryset=VehicleImage.objects.filter(image_type='front'),
                to_attr='front_images'
            )
        )

    if search_query:
        rentals_qs = rentals_qs.filter(vehicle__vehicle_name__icontains=search_query)

    if status_filter == "active":
        rentals_qs = rentals_qs.filter(start_date__lte=today, end_date__gte=today)
    elif status_filter == "upcoming":
        rentals_qs = rentals_qs.filter(start_date__gt=today)
    elif status_filter == "completed":
        rentals_qs = rentals_qs.filter(end_date__lt=today)

    rentals_qs = rentals_qs.annotate(
        duration=ExpressionWrapper(F('end_date') - F('start_date'), output_field=DurationField())
    )

    timeline_qs = rentals_qs.annotate(
        week=TruncWeek('start_date')
    ).values('week').annotate(
        total=Sum('total_price')
    ).order_by('week')

    time_labels = [t['week'].strftime("%d %b") for t in timeline_qs]
    time_values = [t['total'] for t in timeline_qs]

    stats = rentals_qs.aggregate(
        total_trips=Count('id'),
        total_cash=Sum('total_price'),
        max_days=Max('duration')
    )
    total_spend = stats['total_cash'] or 0
    stats['max_days'] = stats['max_days'].days if stats['max_days'] else 0

    favourite_vehicle = rentals_qs.values('vehicle__vehicle_name').annotate(count=Count('id')).order_by('-count').first()
    favourite_vehicle_name = favourite_vehicle['vehicle__vehicle_name'] if favourite_vehicle else "N/A"
    favourite_vehicle_count = favourite_vehicle['count'] if favourite_vehicle else 0

    if total_spend >= 30000: tier = "Elite"; remaining = 0; progress_percent = 100
    elif total_spend >= 15000: tier = "Platinum"; remaining = 30000 - total_spend; progress_percent = int((total_spend / 30000) * 100)
    elif total_spend >= 5000: tier = "Gold"; remaining = 15000 - total_spend; progress_percent = int((total_spend / 15000) * 100)
    else: tier = "Silver"; remaining = 5000 - total_spend; progress_percent = int((total_spend / 5000) * 100)

    cat_data = rentals_qs.values('vehicle__category').annotate(total=Sum('total_price'))
    cat_labels = [c['vehicle__category'] for c in cat_data]
    cat_values = [c['total'] for c in cat_data]

    rentals = []
    for r in rentals_qs.order_by(sort_by):
        r.invoice_no = f"INV-{r.rented_at.year}-{r.id:05d}"
        if r.start_date <= today <= r.end_date: r.status_label = "Active"
        elif r.start_date > today: r.status_label = "Upcoming"
        else: r.status_label = "Completed"
        r.vehicle.front_image = r.vehicle.front_images[0] if hasattr(r.vehicle, 'front_images') and r.vehicle.front_images else None
        rentals.append(r)

    return render(request, "rent_history.html", {
        "rentals": rentals,
        "stats": stats,
        "favourite_vehicle_name": favourite_vehicle_name,
        "favourite_vehicle_count": favourite_vehicle_count,
        "tier": tier,
        "progress_percent": progress_percent,
        "remaining": remaining,
        "cat_labels": json.dumps(cat_labels),
        "cat_values": json.dumps(cat_values),
        "time_labels": json.dumps(time_labels),
        "time_values": json.dumps(time_values),
        "status_filter": status_filter,
    })


# ==========================================
# DRIVERS
# ==========================================

@login_required
def become_driver(request):
    # Check if the user already has an application
    application = DriverApplication.objects.filter(user=request.user).first()
    
    if request.method == "POST":
        full_name = request.POST.get("full_name")
        age = request.POST.get("age")
        phone_number = request.POST.get("phone_number")
        experience_years = request.POST.get("experience_years")
        price_per_day = request.POST.get("price_per_day")
        aadhaar_image = request.FILES.get("aadhaar_image")
        license_image = request.FILES.get("license_image")
        profile_photo = request.FILES.get("profile_photo")

        if application and application.status == 'rejected':
            # Update existing rejected application
            application.full_name = full_name
            application.age = age
            application.phone_number = phone_number
            application.experience_years = experience_years
            application.price_per_day = price_per_day
            if aadhaar_image: application.aadhaar_image = aadhaar_image
            if license_image: application.license_image = license_image
            if profile_photo: application.profile_photo = profile_photo
            application.status = 'pending'
            application.save()
        elif not application:
            # Create new application
            DriverApplication.objects.create(
                user=request.user,
                full_name=full_name,
                age=age,
                phone_number=phone_number,
                experience_years=experience_years,
                price_per_day=price_per_day,
                aadhaar_image=aadhaar_image,
                license_image=license_image,
                profile_photo=profile_photo,
                status='pending'
            )

        messages.success(request, "Your application has been submitted! It is now under review.")
        return redirect("become_driver") # Refresh page to show pending state

    # --- GET REQUEST: Determine what UI to show ---
    context = {'status': 'new'}
    
    if application:
        context['status'] = application.status
        
        if application.status == 'approved':
            # Get driver stats for the dashboard
            driver = Driver.objects.filter(application=application).first()
            if driver:
                total_earned = Rental.objects.filter(driver=driver).aggregate(Sum('total_price'))['total_price__sum'] or 0
                trips_completed = Rental.objects.filter(driver=driver, end_date__lt=date.today()).count()
                
                context['driver'] = driver
                context['total_earned'] = total_earned
                context['trips_completed'] = trips_completed
            else:
                context['status'] = 'pending' # Fallback

    return render(request, "become_driver.html", context)


# ==========================================
# WALLET & PAYMENTS
# ==========================================

@login_required
def payments_view(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')

    context = {
        'wallet': wallet,
        'transactions': transactions,
        'total_spent': wallet.balance,
    }
    return render(request, 'payments.html', context)

@login_required
def create_checkout_session(request):
    if request.method == 'POST':
        try:
            amount_str = request.POST.get('amount', '500')
            amount_inr = int(amount_str)
            amount_paise = amount_inr * 100 

            request.session['recharge_amount'] = amount_inr

            domain_url = 'http://127.0.0.1:8000/'
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'inr',
                        'product_data': {
                            'name': 'Wallet Recharge',
                            'description': f"Add ₹{amount_inr} to GoWheels Wallet",
                        },
                        'unit_amount': amount_paise,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=domain_url + 'payment/success_handler/',
                cancel_url=domain_url + 'payments/',
            )
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('payments')
    return redirect('payments')

@login_required
def payment_success_handler(request):
    amount = request.session.get('recharge_amount')
    
    if amount:
        wallet = request.user.wallet
        
        wallet.balance += amount
        wallet.save()
        
        WalletTransaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='CREDIT',
            description='Wallet Recharge via Stripe'
        )
        
        del request.session['recharge_amount']
        
        return render(request, 'payments.html', {
            'payment_status': 'success',
            'message': f'₹{amount} has been added to your wallet successfully!',
            'wallet': wallet,
            'transactions': WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')
        })
    
    return redirect('payments')

def payment_success(request):
    return render(request, 'payments.html')

def payment_cancel(request):
    return render(request, 'home.html', {'message': 'Payment Cancelled'})

@login_required
def edit_vehicle(request, vehicle_id):
    # Fetch the vehicle and ensure the current user is the owner
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)

    if request.method == "POST":
        # Removed the owner_name line here!
        vehicle.contact_number = request.POST.get('contact_number')
        vehicle.vehicle_name = request.POST.get('vehicle_name')
        vehicle.vehicle_type = request.POST.get('vehicle_type')
        vehicle.category = request.POST.get('category')
        vehicle.price_per_day = request.POST.get('price_per_day')
        vehicle.seats = request.POST.get('seats')
        vehicle.fuel_type = request.POST.get('fuel_type')
        vehicle.pickup_location = request.POST.get('pickup_location')
        
        vehicle.save()
        messages.success(request, f"'{vehicle.vehicle_name}' has been updated successfully!")
        return redirect('your_vehicles')

    return render(request, 'edit_vehicle.html', {'vehicle': vehicle})


from django.http import JsonResponse
from django.views.decorators.http import require_POST

@login_required
@require_POST
def toggle_vehicle_status(request, vehicle_id):
    # Fetch vehicle, ensuring only the owner can modify it
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)
    
    try:
        # Load the JSON data sent from the JavaScript
        data = json.loads(request.body)
        is_available = data.get('available', True)
        
        # Update the database
        vehicle.available = is_available
        vehicle.save()
        
        return JsonResponse({'success': True, 'is_available': vehicle.available})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
def your_vehicles(request):
    # Get only vehicles added by the logged-in user
    vehicles = Vehicle.objects.filter(owner=request.user).order_by('-created_at')

    booked_count = 0
    
    # Attach front images and booked status
    for v in vehicles:
        v.front_image = v.images.filter(image_type="front").first()
        v.is_booked_today = v.is_booked()
        
        # Count how many are currently on a trip today
        if v.is_booked_today:
            booked_count += 1

    # Calculate total revenue generated from all rentals of this owner's vehicles
    earnings_data = Rental.objects.filter(vehicle__owner=request.user).aggregate(total=Sum('total_price'))
    total_earnings = earnings_data['total'] or 0

    return render(request, "your_vehicles.html", {
        "vehicles": vehicles,
        "booked_count": booked_count,       # <--- Passing the active rent count
        "total_earnings": total_earnings    # <--- Passing the total money made
    })  