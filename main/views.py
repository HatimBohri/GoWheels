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
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Prefetch, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Q
from decimal import Decimal

# Import all models correctly
from .models import Driver, Rental, UserProfile, Vehicle, VehicleImage, Wallet, WalletTransaction, Review

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


# ==========================================
# EMAIL HELPER: BOOKING CONFIRMATION
# ==========================================

def send_booking_confirmation_email(request, rental):
    """ Generates and sends a premium HTML email with full billing details """
    try:
        # 1. Dynamic Invoice & Dates
        year = getattr(rental, 'rented_at', timezone.now()).year
        booking_id = f"INV-{year}-{rental.id:05d}"
        domain_url = request.build_absolute_uri('/')
        
        start_dt = rental.start_date if isinstance(rental.start_date, date) else datetime.strptime(rental.start_date, "%Y-%m-%d").date()
        end_dt = rental.end_date if isinstance(rental.end_date, date) else datetime.strptime(rental.end_date, "%Y-%m-%d").date()
        
        start_str = start_dt.strftime("%d %b, %Y")
        end_str = end_dt.strftime("%d %b, %Y")
        
        # 2. Calculate Billing Details
        days = (end_dt - start_dt).days + 1
        vehicle_rate = rental.vehicle.price_per_day
        vehicle_total = vehicle_rate * days
        
        drive_mode = "Self-Drive"
        driver_row_html = ""
        
        # If a driver was selected, calculate their fare separately
        if rental.drive_type == 'driver' and rental.driver:
            drive_mode = f"Chauffeur ({rental.driver.name})"
            driver_rate = rental.driver.price_per_day
            driver_total = driver_rate * days
            driver_row_html = f"""
            <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #555;">Driver Fare ({days} Days @ ₹{driver_rate}/day)</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; text-align: right; font-weight: 500;">₹{driver_total}</td>
            </tr>
            """
            
        # Format Payment Mode
        payment_modes = {'cash': 'Cash on Pickup', 'online': 'Online Payment', 'wallet': 'Paid via Wallet'}
        payment_display = payment_modes.get(rental.payment_mode, rental.payment_mode.title())

        # Check for Promo Code Display
        promo_row_html = ""
        if hasattr(rental, 'promo_code') and rental.promo_code:
            promo_row_html = f"""
            <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #25D366; font-weight: 600;">Promo Applied ({rental.promo_code})</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; text-align: right; font-weight: 600; color: #25D366;">Discount Included</td>
            </tr>
            """

        # Check for Vehicle Number Display
        vehicle_number_html = ""
        if hasattr(rental.vehicle, 'vehicle_number') and rental.vehicle.vehicle_number:
            vehicle_number_html = f"""
            <tr>
                <td style="padding: 8px 0; color: #888;">Vehicle No.</td>
                <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #121212;">{rental.vehicle.vehicle_number}</td>
            </tr>
            """

        # 3. Define the Premium HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
        </head>
        <body style="font-family: 'Poppins', Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 10px;">
            
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.08);">
                
                <div style="background-color: #121212; padding: 40px 20px; text-align: center;">
                    <div style="display: inline-block; background-color: #ff6a2a; color: #000; border-radius: 50%; width: 44px; height: 44px; line-height: 44px; font-size: 22px; font-weight: bold; margin-bottom: 15px;">⚡</div>
                    <h1 style="margin: 0; color: #ffffff; font-size: 26px; font-weight: 700; letter-spacing: 0.5px;">Booking Confirmed!</h1>
                    <p style="color: #a0a0a0; margin: 10px 0 0 0; font-size: 15px;">Your vehicle is reserved and ready.</p>
                </div>

                <div style="padding: 40px 30px;">
                    <p style="margin: 0 0 20px 0; font-size: 16px; color: #333333;">Hi <strong>{rental.full_name}</strong>,</p>
                    <p style="margin: 0 0 30px 0; font-size: 15px; color: #555555; line-height: 1.6;">Thank you for choosing <strong>GoWheels</strong>. Below is the complete summary of your itinerary and billing details.</p>

                    <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #121212; border-bottom: 2px solid #ff6a2a; display: inline-block; padding-bottom: 4px;">Trip Itinerary</h3>
                    <div style="background-color: #fafbfc; border: 1px solid #eaeef2; border-radius: 12px; padding: 20px; margin-bottom: 30px;">
                        <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px; color: #444444;">
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Booking ID</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #121212;">{booking_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Vehicle</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{rental.vehicle.vehicle_name}</td>
                            </tr>
                            {vehicle_number_html}
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Dates</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{start_str} to {end_str}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Drive Mode</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{drive_mode}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Pickup Location</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{rental.vehicle.pickup_location}</td>
                            </tr>
                        </table>
                    </div>

                    <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #121212; border-bottom: 2px solid #ff6a2a; display: inline-block; padding-bottom: 4px;">Payment Summary</h3>
                    <div style="background-color: #ffffff; border: 1px solid #eaeef2; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                        <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px; color: #444444;">
                            <tr>
                                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #555;">Vehicle Fare ({days} Days @ ₹{vehicle_rate}/day)</td>
                                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; text-align: right; font-weight: 500;">₹{vehicle_total}</td>
                            </tr>
                            {driver_row_html}
                            {promo_row_html}
                            <tr>
                                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #555;">Payment Method</td>
                                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; text-align: right; font-weight: 600; color: #28a745;">{payment_display}</td>
                            </tr>
                        </table>

                        <div style="margin-top: 15px; text-align: right;">
                            <span style="font-size: 13px; color: #888888; text-transform: uppercase; letter-spacing: 1px;">Total Amount</span><br>
                            <span style="font-size: 28px; color: #ff6a2a; font-weight: 700;">₹{rental.total_price}</span>
                        </div>
                    </div>

                    <div style="margin-top: 35px; background: linear-gradient(135deg, rgba(255,106,42,0.08), rgba(255,106,42,0.02)); border-left: 4px solid #ff6a2a; padding: 18px 22px; border-radius: 0 10px 10px 0;">
                        <p style="margin: 0 0 12px 0; font-size: 15px; color: #121212; font-weight: 600; letter-spacing: 0.3px;">
                            Pickup Guidelines
                        </p>
                        <ul style="margin: 0; padding-left: 18px; font-size: 13.5px; color: #444; line-height: 1.7;">
                            <li>Please carry your original <strong>Driving License</strong> and <strong>Aadhaar Card</strong> for identity verification.</li>
                            <li>Kindly arrive at least <strong>15 minutes prior</strong> to your scheduled pickup time.</li>
                            <li>Ensure your <strong>driving license is valid</strong> and not expired.</li>
                            <li>Thoroughly inspect the <strong>vehicle’s condition</strong> (interior & exterior) before departure.</li>
                            <li>Confirm availability of all required documents (<strong>RC, Insurance, PUC</strong>).</li>
                            <li>Check <strong>fuel level</strong> and basic functionalities (lights, brakes, indicators).</li>
                            <li>In case of delay, please <strong>inform your host in advance</strong>.</li>
                            <li>Vehicle usage is permitted only for the <strong>registered driver</strong>.</li>
                            <li>Follow all <strong>traffic regulations</strong> during your trip.</li>
                            <li>For any assistance, please <strong>contact support or your host immediately</strong>.</li>
                        </ul>
                    </div>

                    <div style="text-align: center; margin-top: 40px;">
                        <a href="{domain_url}rent-history/" style="display: inline-block; padding: 16px 36px; background-color: #121212; color: #ffffff; text-decoration: none; border-radius: 30px; font-weight: 600; font-size: 15px; letter-spacing: 0.5px; transition: 0.3s;">Manage My Booking</a>
                    </div>
                </div>

                <div style="background-color: #fafbfc; padding: 25px 20px; text-align: center; border-top: 1px solid #eaeef2;">
                    <p style="margin: 0 0 10px 0; font-size: 13px; color: #888888;">Need assistance? Contact our support team at <a href="mailto:support@gowheels.com" style="color: #ff6a2a; text-decoration: none; font-weight: 500;">support@gowheels.com</a></p>
                    <p style="margin: 0; font-size: 12px; color: #aaaaaa;">&copy; {year} GoWheels Premium Rentals. All rights reserved.</p>
                </div>

            </div>
        </body>
        </html>
        """

        # 4. Extract plain text automatically for email clients that don't support HTML
        text_content = strip_tags(html_content)

        # 5. Send Email
        send_mail(
            subject=f"Booking Confirmed: {rental.vehicle.vehicle_name} 🚗 | GoWheels",
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
            fail_silently=True,
            html_message=html_content
        )
        print(f"🔥 [DEVELOPER CONSOLE] Premium confirmation email sent to {request.user.email}")
        
    except Exception as e:
        print(f"❌ [EMAIL ERROR] Failed to send confirmation: {e}")


def send_host_notification_email(request, rental):
    """ Generates and sends a highly detailed, premium HTML notification to the vehicle host """
    try:
        host_email = rental.vehicle.owner.email
        if not host_email:
            return # Skip if host has no email configured

        year = getattr(rental, 'rented_at', timezone.now()).year
        booking_id = f"INV-{year}-{rental.id:05d}"
        domain_url = request.build_absolute_uri('/')
        
        start_dt = rental.start_date if isinstance(rental.start_date, date) else datetime.strptime(rental.start_date, "%Y-%m-%d").date()
        end_dt = rental.end_date if isinstance(rental.end_date, date) else datetime.strptime(rental.end_date, "%Y-%m-%d").date()
        
        start_str = start_dt.strftime("%d %b, %Y")
        end_str = end_dt.strftime("%d %b, %Y")
        days = (end_dt - start_dt).days + 1
        
        drive_mode = "Self-Drive"
        if rental.drive_type == 'driver' and rental.driver:
            drive_mode = f"Chauffeur ({rental.driver.name})"
            
        payment_modes = {'cash': 'Cash on Pickup', 'online': 'Online Payment', 'wallet': 'Paid via Wallet', 'upi': 'UPI Payment'}
        payment_display = payment_modes.get(rental.payment_mode, rental.payment_mode.title())

        # Premium HTML Template for Host with Detailed Instructions
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
        </head>
        <body style="font-family: 'Poppins', Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 10px;">
            <div style="max-width: 650px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.08);">
                
                <div style="background-color: #121212; padding: 40px 20px; text-align: center;">
                    <div style="display: inline-block; background-color: #28c76f; color: #000; border-radius: 50%; width: 48px; height: 48px; line-height: 48px; font-size: 24px; font-weight: bold; margin-bottom: 15px;">🚗</div>
                    <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: 0.5px;">New Booking Confirmed</h1>
                    <p style="color: #a0a0a0; margin: 10px 0 0 0; font-size: 15px;">Action Required: Please prepare your vehicle for handover.</p>
                </div>

                <div style="padding: 40px 30px;">
                    <p style="margin: 0 0 20px 0; font-size: 16px; color: #333333;">Hello <strong>{rental.vehicle.owner.first_name or rental.vehicle.owner.username}</strong>,</p>
                    <p style="margin: 0 0 30px 0; font-size: 15px; color: #555555; line-height: 1.6;">Excellent news! A renter has successfully booked your <strong>{rental.vehicle.vehicle_name}</strong> for an upcoming trip. Please review the booking details and strict handover instructions below to ensure a smooth and secure process.</p>

                    <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #121212; border-bottom: 2px solid #28c76f; display: inline-block; padding-bottom: 4px;">Booking Summary</h3>
                    <div style="background-color: #fafbfc; border: 1px solid #eaeef2; border-radius: 12px; padding: 20px; margin-bottom: 35px;">
                        <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px; color: #444444;">
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Booking ID</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 700; color: #121212;">{booking_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888; border-top: 1px solid #eee;">Renter Name</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #121212; border-top: 1px solid #eee;">{rental.full_name}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Contact Phone</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{rental.phone_number}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888; border-top: 1px solid #eee;">Duration</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500; border-top: 1px solid #eee;">{start_str} to {end_str} ({days} Days)</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888;">Drive Mode</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 500;">{drive_mode}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #888; border-top: 1px solid #eee;">Payment Method</td>
                                <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #ff6a2a; border-top: 1px solid #eee;">{payment_display} (Total: ₹{rental.total_price})</td>
                            </tr>
                        </table>
                    </div>

                    <h3 style="margin: 0 0 15px 0; font-size: 16px; color: #121212; border-bottom: 2px solid #ff6a2a; display: inline-block; padding-bottom: 4px;">Host Protocol & Guidelines</h3>
                    <p style="font-size: 14px; color: #666; margin-bottom: 20px;">To protect your asset and provide a 5-star experience, please strictly adhere to the following checklist.</p>

                    <div style="margin-bottom: 25px;">
                        <div style="font-weight: 600; color: #121212; font-size: 15px; margin-bottom: 10px; display: flex; align-items: center;"><span style="background: #eef2f5; color: #555; border-radius: 50%; width: 24px; height: 24px; display: inline-block; text-align: center; line-height: 24px; font-size: 12px; margin-right: 10px;">1</span> Pre-Trip Preparation</div>
                        <ul style="margin: 0; padding-left: 35px; font-size: 13.5px; color: #444; line-height: 1.7;">
                            <li>Clean the vehicle thoroughly (exterior wash and interior vacuum).</li>
                            <li>Check essential fluids (engine oil, coolant, windshield washer).</li>
                            <li>Ensure optimum tire pressure (including the spare tire).</li>
                            <li>Verify that all mandatory documents (Original/Copy of RC, valid Insurance, and valid PUC) are securely placed in the glovebox.</li>
                        </ul>
                    </div>

                    <div style="margin-bottom: 25px;">
                        <div style="font-weight: 600; color: #121212; font-size: 15px; margin-bottom: 10px; display: flex; align-items: center;"><span style="background: #ff6a2a; color: #fff; border-radius: 50%; width: 24px; height: 24px; display: inline-block; text-align: center; line-height: 24px; font-size: 12px; margin-right: 10px;">2</span> Handover Checklist (Mandatory)</div>
                        <ul style="margin: 0; padding-left: 35px; font-size: 13.5px; color: #444; line-height: 1.7;">
                            <li><strong>Identity Verification:</strong> Physically verify the renter's original Driving License and Aadhaar Card. The person picking up the car <span style="color:#d9534f; font-weight:bold;">must</span> be the person who booked it.</li>
                            <li><strong>Capture Evidence:</strong> Take clear photos or a continuous video of the vehicle's exterior (all 4 sides) and interior to document pre-existing scratches/dents.</li>
                            <li><strong>Dashboard Reading:</strong> Take a clear photo of the dashboard showing the <strong>Current Odometer reading</strong> and <strong>Fuel Level</strong>. Share these with the renter on WhatsApp for mutual agreement.</li>
                            {f"<li><strong>Payment Collection:</strong> Since this is a Cash on Pickup booking, strictly collect <strong>₹{rental.total_price}</strong> before handing over the keys.</li>" if rental.payment_mode == 'cash' else ""}
                        </ul>
                    </div>

                    <div style="margin-bottom: 25px;">
                        <div style="font-weight: 600; color: #121212; font-size: 15px; margin-bottom: 10px; display: flex; align-items: center;"><span style="background: #28c76f; color: #fff; border-radius: 50%; width: 24px; height: 24px; display: inline-block; text-align: center; line-height: 24px; font-size: 12px; margin-right: 10px;">3</span> Vehicle Return</div>
                        <ul style="margin: 0; padding-left: 35px; font-size: 13.5px; color: #444; line-height: 1.7;">
                            <li>Inspect the vehicle against the photos taken during handover.</li>
                            <li>Verify the fuel level matches the handover level.</li>
                            <li>Once the trip is completed safely, log in to your dashboard to mark the trip as "Completed" and report any damages or late fees if applicable.</li>
                        </ul>
                    </div>
                    
                    <div style="text-align: center; margin-top: 45px;">
                        <a href="{domain_url}your-vehicles/" style="display: inline-block; padding: 16px 36px; background-color: #121212; color: #ffffff; text-decoration: none; border-radius: 30px; font-weight: 600; font-size: 15px; letter-spacing: 0.5px; transition: 0.3s; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">Manage Dashboard</a>
                    </div>
                </div>
                
                <div style="background-color: #fafbfc; padding: 25px 20px; text-align: center; border-top: 1px solid #eaeef2;">
                    <p style="margin: 0 0 10px 0; font-size: 13px; color: #888888;">If you detect any fraud or need emergency assistance, contact Host Support immediately at <a href="mailto:host-support@gowheels.com" style="color: #28c76f; text-decoration: none; font-weight: 600;">host-support@gowheels.com</a></p>
                    <p style="margin: 0; font-size: 12px; color: #aaaaaa;">&copy; {year} GoWheels Premium Rentals. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = strip_tags(html_content)

        send_mail(
            subject=f"Action Required: New Booking Confirmed - {rental.vehicle.vehicle_name} 🚗 | GoWheels",
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[host_email],
            fail_silently=True,
            html_message=html_content
        )
        print(f"🔥 [DEVELOPER CONSOLE] Premium host protocol email sent to {host_email}")
        
    except Exception as e:
        print(f"❌ [EMAIL ERROR] Failed to send host confirmation: {e}")

# ==========================================
# GENERAL PAGES
# ==========================================

def home(request):
    pending_review = None
    if request.user.is_authenticated:
        today = timezone.now().date()
        pending_review = Rental.objects.filter(
            user=request.user, end_date__lt=today, review__isnull=True
        ).select_related('vehicle').order_by('-end_date').first()
        
    return render(request, 'home.html', {'pending_review': pending_review})


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
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 36)

    for _ in range(1200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(0, 0, 255))

    for i, char in enumerate(captcha_text):
        x = 15 + i * 28 + random.randint(-3, 3)
        y = random.randint(5, 15)
        draw.text((x, y), char, font=font, fill=(0, 0, 0))

    image = image.filter(ImageFilter.GaussianBlur(0.6))

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)

    return HttpResponse(buffer, content_type="image/png")


# ==========================================
# REAL-TIME OTP API
# ==========================================

@csrf_exempt
def send_otp_api(request):
    if request.method == "POST":
        email = request.POST.get("email")
        if not email:
            return JsonResponse({"status": "error", "message": "Email is required."})

        otp_code = str(random.randint(100000, 999999))
        request.session['saved_otp'] = otp_code
        request.session['otp_email'] = email

        try:
            send_mail(
                subject='GoWheels - Your Verification Code',
                message=f'Your secure GoWheels OTP is: {otp_code}. Do not share this with anyone.',
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@gowheels.com',
                recipient_list=[email],
                fail_silently=True,
            )
            return JsonResponse({"status": "success", "message": "OTP Sent Successfully!"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request."})


# ==========================================
# AUTHENTICATION & SIGNUP
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        lockout_key = f"lockout_{username}"
        attempts_key = f"attempts_{username}"

        if cache.get(lockout_key):
            messages.error(request, "Too many failed attempts. Garage locked for 2 minutes.")
            return render(request, 'login.html')

        user = authenticate(request, username=username, password=password)
        
        if user:
            cache.delete(attempts_key)
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or username}!")
            return redirect('home')
        else:
            attempts = cache.get(attempts_key, 0) + 1
            cache.set(attempts_key, attempts, timeout=300)
            
            if attempts >= 5:
                cache.set(lockout_key, True, timeout=120)
                cache.delete(attempts_key) 
                messages.error(request, "Account temporarily locked due to 5 failed attempts. Try again in 2 minutes.")
            else:
                messages.error(request, f"Invalid username or password! ({5 - attempts} attempts remaining)")

    return render(request, 'login.html')


def signup_view(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        email = request.POST.get("email")
        phone_number = request.POST.get("phone_number")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        user_otp = request.POST.get("otp_code")

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, "signup.html")

        username = email 
        if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists!")
            return render(request, "signup.html")

        saved_otp = request.session.get('saved_otp')
        saved_email = request.session.get('otp_email')

        if not saved_otp or not user_otp or saved_otp != user_otp or saved_email != email:
            messages.error(request, "Invalid or Expired OTP. Please try again.")
            return render(request, "signup.html")

        user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name)
        user.profile.phone_number = phone_number
        user.profile.save()

        del request.session['saved_otp']
        del request.session['otp_email']

        messages.success(request, "Engine Started! Account created successfully. Please log in.")
        return redirect("login")

    return render(request, "signup.html")


def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")
        user = User.objects.filter(email=email).first()

        if user:
            otp_code = str(random.randint(100000, 999999))
            request.session['reset_otp'] = otp_code
            request.session['reset_email'] = email
            
            send_mail(
                'GoWheels - Password Reset',
                f'Your password reset code is: {otp_code}',
                'noreply@gowheels.com',
                [email],
                fail_silently=True,
            )
            messages.success(request, "If that email exists, an OTP has been sent.")
            return redirect('reset_password')
        else:
            messages.success(request, "If that email exists, an OTP has been sent.")
            return redirect('reset_password')

    return render(request, 'forgot_password.html')


def reset_password(request):
    if request.method == "POST":
        email = request.session.get('reset_email')
        otp_input = request.POST.get("otp_code")
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")
        saved_otp = request.session.get('reset_otp')

        if not email or not saved_otp:
            messages.error(request, "Session expired. Please request a new OTP.")
            return redirect('forgot_password')

        if otp_input != saved_otp:
            messages.error(request, "Invalid OTP code.")
            return redirect('reset_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('reset_password')

        user = User.objects.get(email=email)
        user.set_password(new_password)
        user.save()

        del request.session['reset_otp']
        del request.session['reset_email']

        messages.success(request, "Password successfully reset! You can now log in.")
        return redirect('login')

    return render(request, 'reset_password.html')


# ==========================================
# VEHICLES & SEARCH
# ==========================================

@login_required(login_url='login')
def list_vehicle(request):
    if request.method == "POST":
        vehicle = Vehicle.objects.create(
            owner=request.user, contact_number=request.POST['contact_number'],
            vehicle_name=request.POST['vehicle_name'], vehicle_type=request.POST['vehicle_type'],
            vehicle_number=request.POST.get('vehicle_number', ''),
            category=request.POST['category'], price_per_day=request.POST['price_per_day'],
            seats=request.POST.get('seats') or None, fuel_type=request.POST['fuel_type'],
            pickup_location=request.POST['pickup_location'],
        )

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

    # ==========================================
    # 1. PROFESSIONAL MULTI-COLUMN SEARCH LOGIC
    # ==========================================
    search_query = request.GET.get('search', '').strip()
    if search_query:
        # This searches the Name, Category, Vehicle Type, AND Pickup Location
        qs = qs.filter(
            Q(vehicle_name__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(vehicle_type__icontains=search_query) |
            Q(pickup_location__icontains=search_query)
        )

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

    if min_price:
        try: qs = qs.filter(price_per_day__gte=float(min_price))
        except ValueError: pass
        
    if max_price:
        try: qs = qs.filter(price_per_day__lte=float(max_price))
        except ValueError: pass

    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            if start <= end:
                booked_ids = Rental.objects.filter(start_date__lte=end, end_date__gte=start).values_list("vehicle_id", flat=True)
                qs = qs.exclude(id__in=booked_ids)
        except ValueError:
            messages.error(request, "Invalid date format used in filter.")

    if selected_categories and "All" not in selected_categories:
        search_cats = []
        for c in selected_categories: search_cats.extend([c, c.lower(), c.capitalize(), c.upper(), c.title()])
        qs = qs.filter(category__in=search_cats)

    if selected_vehicle_types:
        search_types = []
        for vt in selected_vehicle_types: search_types.extend([vt, vt.lower(), vt.capitalize(), vt.upper()])
        qs = qs.filter(vehicle_type__in=search_types)

    if selected_fuels:
        search_fuels = []
        for f in selected_fuels: search_fuels.extend([f, f.lower(), f.capitalize(), f.upper()])
        qs = qs.filter(fuel_type__in=search_fuels)

    if seats:
        try:
            seats_val = int(seats)
            qs = qs.filter(seats__gte=12) if seats_val == 12 else qs.filter(seats=seats_val)
        except ValueError: pass

    today = timezone.now().date()
    if status_filters:
        if "available" in status_filters and "soon" not in status_filters:
            qs = qs.filter(available=True).exclude(rental__start_date__lte=today, rental__end_date__gte=today)
        elif "soon" in status_filters and "available" not in status_filters:
            qs = qs.filter(available=True, rental__start_date__lte=today, rental__end_date__gte=today).distinct()
        elif "available" in status_filters and "soon" in status_filters:
            qs = qs.filter(available=True)

    if sort == "price_low": qs = qs.order_by("price_per_day")
    elif sort == "price_high": qs = qs.order_by("-price_per_day")
    else: qs = qs.order_by("vehicle_name")  # Alphabetical mix

    for v in qs:
        v.front_image = v.images.filter(image_type="front").first()
        
        # Robust fallback to guarantee the "is_booked_today" flag works
        is_booked_now = Rental.objects.filter(vehicle=v, start_date__lte=today, end_date__gte=today).exists()
        v.is_booked_today = getattr(v, 'is_booked', lambda: is_booked_now)() if hasattr(v, 'is_booked') else is_booked_now
        
        if v.is_booked_today:
            # Find the date it will be free again
            next_rental = Rental.objects.filter(vehicle=v, end_date__gte=today).order_by('-end_date').first()
            if next_rental:
                v.available_from = next_rental.end_date + timedelta(days=1)

    return render(request, "vehicles.html", {
        "vehicles": qs, "categories": Vehicle.CATEGORY_CHOICES, "fuel_choices": Vehicle.FUEL_CHOICES,
        "selected_categories": selected_categories, "selected_vehicle_types": selected_vehicle_types,
        "selected_fuels": selected_fuels, "selected_seats": seats, "selected_statuses": status_filters, "request": request,
    })


@login_required
def your_vehicles(request):
    vehicles = Vehicle.objects.filter(owner=request.user).order_by('-created_at')
    booked_count = 0
    today = timezone.now().date()
    
    for v in vehicles:
        v.front_image = v.images.filter(image_type="front").first()
        is_booked_now = Rental.objects.filter(vehicle=v, start_date__lte=today, end_date__gte=today).exists()
        v.is_booked_today = getattr(v, 'is_booked', lambda: is_booked_now)() if hasattr(v, 'is_booked') else is_booked_now
        
        if v.is_booked_today: 
            booked_count += 1
            
        # NEW: Fetch active rentals for this vehicle so the host can mark them complete
        # Assumes you added the 'status' field as discussed previously. 
        # If not, use: Rental.objects.filter(vehicle=v, end_date__gte=today)
        v.active_rentals = Rental.objects.filter(vehicle=v, status='ACTIVE').order_by('start_date')

    earnings_data = Rental.objects.filter(vehicle__owner=request.user).aggregate(total=Sum('total_price'))
    total_earnings = earnings_data['total'] or 0

    return render(request, "your_vehicles.html", {"vehicles": vehicles, "booked_count": booked_count, "total_earnings": total_earnings})


# ==========================================
# RENTALS, BOOKINGS & REVIEWS
# ==========================================

def vehicle_booked_dates(request, vehicle_id):
    bookings = Rental.objects.filter(vehicle_id=vehicle_id).values('start_date', 'end_date')
    return JsonResponse(list(bookings), safe=False)


def is_vehicle_available(vehicle, start_date, end_date):
    return not Rental.objects.filter(vehicle=vehicle, start_date__lte=end_date, end_date__gte=start_date).exists()


@login_required
def rent_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)
    available_drivers = Driver.objects.filter(available=True)
    user_wallet, _ = Wallet.objects.get_or_create(user=request.user)

    # 1. Check if this user has ever rented before (for FIRST200)
    is_new_user = not Rental.objects.filter(user=request.user).exists()

    # Fetch all upcoming bookings for this vehicle to pass to frontend JSON
    # Exclude cancelled or completed ones so they don't block availability
    future_rentals = Rental.objects.filter(
        vehicle=vehicle, 
        end_date__gte=timezone.now().date()
    ).exclude(status__in=['CANCELLED', 'COMPLETED'])
    booked_dates_list = [{'start': r.start_date.strftime("%Y-%m-%d"), 'end': r.end_date.strftime("%Y-%m-%d")} for r in future_rentals]

    # --- Fetch future driver bookings to pass to Javascript ---
    driver_bookings = list(Rental.objects.filter(
        driver__isnull=False, 
        end_date__gte=timezone.now().date()
    ).exclude(status__in=['CANCELLED', 'COMPLETED']).values('driver_id', 'start_date', 'end_date'))
    
    # Format the dates into strings for JSON serialization
    for db in driver_bookings:
        db['start_date'] = db['start_date'].strftime("%Y-%m-%d")
        db['end_date'] = db['end_date'].strftime("%Y-%m-%d")

    if request.method == "POST":
        captcha_input = request.POST.get("captcha_input", "").upper()
        captcha_code = request.session.get("captcha_code")
        if not captcha_code or captcha_input != captcha_code:
            messages.error(request, "Invalid captcha.")
            return redirect(request.path)
        del request.session['captcha_code']

        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        drive_type = request.POST.get("drive_type") or "self"
        driver_id = request.POST.get("driver_id")
        payment_mode = request.POST.get("payment_mode")
        
        full_name = request.POST.get("full_name")
        age = request.POST.get("age")
        phone_number = request.POST.get("phone_number")
        aadhaar_image = request.FILES.get("aadhaar_image")
        license_image = request.FILES.get("license_image")

        special_notes = request.POST.get("special_notes", "")
        promo_code = request.POST.get("promo_code", "").strip().upper()

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

        # --- Validate Driver Availability ---
        if drive_type == "driver" and driver_id:
            selected_driver = Driver.objects.get(id=int(driver_id))
            
            # Check if driver is already booked for these dates
            if not selected_driver.is_available_for_dates(start, end):
                messages.error(request, f"Sorry, Driver {selected_driver.name} is already booked on these dates. Please select another driver or change your dates.")
                return redirect(request.path)
                
            total_price += days * selected_driver.price_per_day

        # --- APPLY BACKEND PROMO CODE LOGIC ---
        base_total = total_price
        discount_amt = 0

        # Weekend Check
        has_weekend = any((start + timedelta(days=i)).weekday() in [5, 6] for i in range(days))

        if promo_code == "VIP25" and base_total >= 10000:
            discount_amt = base_total * 0.25
        elif promo_code == "FIRST200" and is_new_user:
            discount_amt = 200
        elif promo_code == "EASY500":
            discount_amt = 500
        elif promo_code == "GO10":
            discount_amt = base_total * 0.10
        elif promo_code == "LONG10" and days >= 5:
            discount_amt = base_total * 0.10
        elif promo_code == "WEEKEND150" and has_weekend:
            discount_amt = 150
            
        # Make sure the discount doesn't exceed the total price
        if discount_amt > total_price:
            discount_amt = total_price
            
        total_price = Decimal(str(total_price)) - Decimal(str(discount_amt))

        # --- PAYMENT LOGIC ---
        if payment_mode == 'wallet':
            if user_wallet.balance >= total_price:
                user_wallet.balance -= total_price
                user_wallet.save()
                WalletTransaction.objects.create(
                    wallet=user_wallet, amount=total_price, transaction_type='DEBIT',
                    description=f"Rental: {vehicle.vehicle_name}", status='SUCCESS'
                )
                
                rental = Rental.objects.create(
                    user=request.user, vehicle=vehicle, driver=selected_driver,
                    start_date=start, end_date=end, total_price=total_price,
                    full_name=full_name, age=age, phone_number=phone_number,
                    drive_type=drive_type, payment_mode='wallet',
                    aadhaar_image=aadhaar_image, license_image=license_image,
                    special_notes=special_notes, promo_code=promo_code
                )
                
                send_booking_confirmation_email(request, rental)
                send_host_notification_email(request, rental)  # <-- Added Host Notification
                
                messages.success(request, f"Booking Successful! ₹{total_price} paid via Wallet.")
                return redirect("rent_history")
            else:
                messages.error(request, f"Insufficient Wallet Balance (Required: ₹{total_price})")
                return redirect(request.path)

        elif payment_mode == 'online':
            request.session['booking_data'] = {
                'vehicle_id': vehicle.id, 'start_date': start_date, 'end_date': end_date,
                'total_price': float(total_price), 'full_name': full_name, 'age': age,
                'phone_number': phone_number, 'drive_type': drive_type, 'driver_id': driver_id,
                'payment_mode': 'online',
                'special_notes': special_notes,
                'promo_code': promo_code
            }

            paise_amount = int(Decimal(str(total_price)) * 100)
            domain_url = request.build_absolute_uri('/')
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': { 
                        'currency': 'inr', 
                        'product_data': {'name': f"Rent {vehicle.vehicle_name}"}, 
                        'unit_amount': paise_amount,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=domain_url + 'rent/success/', 
                cancel_url=domain_url + f'rent/{vehicle.id}/',
            )
            return redirect(checkout_session.url, code=303)

        elif payment_mode == 'upi':
            utr_number = request.POST.get("upi_utr", "Not Provided")
            combined_notes = special_notes + f" [UPI UTR: {utr_number}]" if special_notes else f"[UPI UTR: {utr_number}]"
            
            rental = Rental.objects.create(
                user=request.user, vehicle=vehicle, driver=selected_driver,
                start_date=start, end_date=end, total_price=total_price,
                full_name=full_name, age=age, phone_number=phone_number,
                drive_type=drive_type, payment_mode='upi',
                aadhaar_image=aadhaar_image, license_image=license_image,
                special_notes=combined_notes, promo_code=promo_code
            )
            
            send_booking_confirmation_email(request, rental)
            send_host_notification_email(request, rental)  # <-- Added Host Notification
            
            messages.success(request, f"Booking Confirmed! Your UPI Payment (UTR: {utr_number}) is under review.")
            return redirect("rent_history")

        else: # CASH
            rental = Rental.objects.create(
                user=request.user, vehicle=vehicle, driver=selected_driver,
                start_date=start, end_date=end, total_price=total_price,
                full_name=full_name, age=age, phone_number=phone_number,
                drive_type=drive_type, payment_mode='cash',
                aadhaar_image=aadhaar_image, license_image=license_image,
                special_notes=special_notes, promo_code=promo_code
            )
            
            send_booking_confirmation_email(request, rental)
            send_host_notification_email(request, rental)  # <-- Added Host Notification
            
            messages.success(request, "Booking Confirmed! Please pay cash on pickup.")
            return redirect("rent_history")

    return render(request, "rent_vehicle.html", {
        "vehicle": vehicle, 
        "available_drivers": available_drivers, 
        "wallet_balance": user_wallet.balance,
        "booked_dates_json": json.dumps(booked_dates_list),
        "driver_bookings_json": json.dumps(driver_bookings),  # <-- Passed to template
        "is_new_user": is_new_user
    })


def finalize_booking(request):
    data = request.session.get('booking_data')
    if not data: return redirect('home')

    vehicle = Vehicle.objects.get(id=data['vehicle_id'])
    selected_driver = Driver.objects.get(id=int(data['driver_id'])) if data.get('driver_id') else None

    rental = Rental.objects.create(
        user=request.user, vehicle=vehicle, driver=selected_driver,
        start_date=data['start_date'], end_date=data['end_date'],
        total_price=data['total_price'], full_name=data['full_name'],
        age=data['age'], phone_number=data['phone_number'],
        drive_type=data['drive_type'], payment_mode=data['payment_mode'],
        special_notes=data.get('special_notes', ''),
        promo_code=data.get('promo_code', ''),
    )
    
    del request.session['booking_data']
    send_booking_confirmation_email(request, rental)
    send_host_notification_email(request, rental)  # <-- Added Host Notification
    
    messages.success(request, "Booking Confirmed Successfully!")
    return redirect("rent_history")


@login_required
def rent_success_callback(request):
    return finalize_booking(request)


@login_required
def submit_review(request):
    if request.method == "POST":
        rental_id = request.POST.get('rental_id')
        rental = get_object_or_404(Rental, id=rental_id, user=request.user)
        
        if not hasattr(rental, 'review') and rental.end_date < timezone.now().date():
            driver_rating = request.POST.get('driver_rating')
            driver_rating_val = int(driver_rating) if driver_rating else None

            Review.objects.create(
                rental=rental, vehicle=rental.vehicle, driver=rental.driver, user=request.user,
                cleanliness=int(request.POST.get('cleanliness', 5)),
                performance=int(request.POST.get('performance', 5)),
                comfort=int(request.POST.get('comfort', 5)),
                driver_rating=driver_rating_val,
                comment=request.POST.get('comment', '')
            )
            
            if rental.driver and driver_rating_val: rental.driver.update_rating()
            messages.success(request, "Review submitted! Thank you for your feedback.")
        
    return redirect('rent_history')

# ==========================================
# DASHBOARD / USER GRAPHICS
# ==========================================

@login_required
def auto_fix_graph(request):
    user = request.user
    vehicle = Vehicle.objects.first()
    if not vehicle:
        vehicle = Vehicle.objects.create(
            owner=user, vehicle_name="Test Graph Car", contact_number="0000000000",
            vehicle_type="car", category="Sedan", price_per_day=1000,
            fuel_type="Petrol", pickup_location="Test City"
        )

    dates = [ date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 20), date(2026, 1, 28), date(2026, 2, 5) ]
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
                user=user, vehicle=vehicle, start_date=start_dt, end_date=end_dt, total_price=price,
                full_name=user.get_full_name() or user.username, age=25, phone_number="9999999999",
                drive_type="self", payment_mode="online",
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
    if sort_by not in allowed_sorts: sort_by = '-rented_at'

    rentals_qs = Rental.objects.filter(user=request.user).select_related('vehicle', 'driver', 'review').prefetch_related(
        Prefetch('vehicle__images', queryset=VehicleImage.objects.filter(image_type='front'), to_attr='front_images')
    )

    if search_query: rentals_qs = rentals_qs.filter(vehicle__vehicle_name__icontains=search_query)

    if status_filter == "active": rentals_qs = rentals_qs.filter(start_date__lte=today, end_date__gte=today)
    elif status_filter == "upcoming": rentals_qs = rentals_qs.filter(start_date__gt=today)
    elif status_filter == "completed": rentals_qs = rentals_qs.filter(end_date__lt=today)

    rentals_qs = rentals_qs.annotate(duration=ExpressionWrapper(F('end_date') - F('start_date'), output_field=DurationField()))

    timeline_qs = rentals_qs.annotate(week=TruncWeek('start_date')).values('week').annotate(total=Sum('total_price')).order_by('week')
    time_labels = [t['week'].strftime("%d %b") for t in timeline_qs]
    time_values = [float(t['total']) if t['total'] else 0 for t in timeline_qs]

    stats = rentals_qs.aggregate(total_trips=Count('id'), total_cash=Sum('total_price'), max_days=Max('duration'))
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
    cat_values = [float(c['total']) if c['total'] else 0 for c in cat_data]

    rentals = []
    for r in rentals_qs.order_by(sort_by):
        r.invoice_no = f"INV-{getattr(r, 'rented_at', r.start_date).year}-{r.id:05d}"
        if r.start_date <= today <= r.end_date: r.status_label = "Active"
        elif r.start_date > today: r.status_label = "Upcoming"
        else: r.status_label = "Completed"
        
        r.vehicle.front_image = r.vehicle.front_images[0] if hasattr(r.vehicle, 'front_images') and r.vehicle.front_images else None
        
        days = (r.end_date - r.start_date).days + 1
        r.days_count = days
        r.vehicle_fare = r.vehicle.price_per_day * days
        r.driver_fare = r.driver.price_per_day * days if r.drive_type == 'driver' and r.driver else 0
        rentals.append(r)

    return render(request, "rent_history.html", {
        "rentals": rentals, "stats": stats, "favourite_vehicle_name": favourite_vehicle_name,
        "favourite_vehicle_count": favourite_vehicle_count, "tier": tier, "progress_percent": progress_percent,
        "remaining": remaining, "cat_labels": json.dumps(cat_labels), "cat_values": json.dumps(cat_values),
        "time_labels": json.dumps(time_labels), "time_values": json.dumps(time_values), "status_filter": status_filter,
    })


# ==========================================
# WALLET & PAYMENTS
# ==========================================

@login_required
def payments_view(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')
    return render(request, 'payments.html', {'wallet': wallet, 'transactions': transactions, 'total_spent': wallet.balance})


@login_required
def create_checkout_session(request):
    if request.method == 'POST':
        try:
            amount_str = request.POST.get('amount', '500')
            amount_inr = int(amount_str)
            amount_paise = amount_inr * 100 
            request.session['recharge_amount'] = amount_inr
            domain_url = request.build_absolute_uri('/')
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': { 'currency': 'inr', 'product_data': { 'name': 'Wallet Recharge', 'description': f"Add ₹{amount_inr} to GoWheels Wallet" }, 'unit_amount': amount_paise },
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
        WalletTransaction.objects.create(wallet=wallet, amount=amount, transaction_type='CREDIT', description='Wallet Recharge via Stripe')
        del request.session['recharge_amount']
        
        return render(request, 'payments.html', {
            'payment_status': 'success', 'message': f'₹{amount} has been added to your wallet successfully!',
            'wallet': wallet, 'transactions': WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')
        })
    return redirect('payments')


def payment_success(request):
    return render(request, 'payments.html')


def payment_cancel(request):
    return render(request, 'home.html', {'message': 'Payment Cancelled'})


@login_required
def edit_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)

    if request.method == "POST":
        vehicle.contact_number = request.POST.get('contact_number')
        vehicle.vehicle_name = request.POST.get('vehicle_name')
        vehicle.vehicle_number = request.POST.get('vehicle_number', '')
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


@login_required
@require_POST
def toggle_vehicle_status(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=request.user)
    try:
        data = json.loads(request.body)
        vehicle.available = data.get('available', True)
        vehicle.save()
        return JsonResponse({'success': True, 'is_available': vehicle.available})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


from django.db import transaction
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .models import Rental, WalletTransaction # Ensure these are imported

@login_required
@require_POST
@transaction.atomic
def complete_rental_by_host(request, rental_id):
    """ Handles the host marking a trip as complete, assessing damages, and billing. """
    rental = get_object_or_404(Rental, id=rental_id, vehicle__owner=request.user)

    if getattr(rental, 'status', '') != 'ACTIVE':
        messages.error(request, "This trip has already been completed or cancelled.")
        return redirect('your_vehicles')

    return_date_str = request.POST.get('actual_return_date', str(timezone.now().date()))
    damage_amount = Decimal(request.POST.get('damage_amount', '0.00') or '0.00')
    host_notes = request.POST.get('host_notes', '')

    actual_return_date = datetime.strptime(return_date_str, "%Y-%m-%d").date()
    
    # 1. Calculate Late Penalties
    late_days = (actual_return_date - rental.end_date).days
    late_penalty = Decimal('0.00')
    
    if late_days > 0:
        daily_rate = Decimal(str(rental.vehicle.price_per_day))
        late_penalty = Decimal(late_days) * (daily_rate * Decimal('1.5'))

    total_penalty = late_penalty + damage_amount

    # 2. Process Wallet & Security Deposit
    user_wallet = getattr(rental.user, 'wallet', None)
    if user_wallet:
        deposit_held = getattr(rental, 'security_deposit_held', Decimal('0.00'))
        refund_amount = deposit_held - total_penalty

        if refund_amount > 0:
            user_wallet.balance += refund_amount
            WalletTransaction.objects.create(
                wallet=user_wallet, amount=refund_amount, transaction_type='CREDIT',
                description=f'Deposit Refund (Trip #{rental.id})'
            )
        elif refund_amount < 0:
            amount_owed = abs(refund_amount)
            user_wallet.balance -= amount_owed
            WalletTransaction.objects.create(
                wallet=user_wallet, amount=amount_owed, transaction_type='DEBIT',
                description=f'Damage/Late Penalties (Trip #{rental.id})'
            )
        user_wallet.save()

    # 3. Update the Rental Record
    rental.status = 'COMPLETED'
    if hasattr(rental, 'actual_return_date'): rental.actual_return_date = actual_return_date
    if hasattr(rental, 'penalty_applied'): rental.penalty_applied = total_penalty
    
    # FIX: Safely handle NoneType for special_notes
    closure_notes = f"\n\n--- HOST CLOSURE NOTES ---\nDamages: ₹{damage_amount}\nLate Days: {late_days}\nNotes: {host_notes}"
    if rental.special_notes:
        rental.special_notes += closure_notes
    else:
        rental.special_notes = closure_notes.strip()
        
    rental.save()

    messages.success(request, f"Trip #{rental.id} successfully completed. Total penalties applied: ₹{total_penalty}.")
    return redirect('your_vehicles')

@login_required
@require_POST
@transaction.atomic
def cancel_rental_by_host(request, rental_id):
    """ Handles the host cancelling a trip because the user didn't show up. """
    rental = get_object_or_404(Rental, id=rental_id, vehicle__owner=request.user)
    
    if getattr(rental, 'status', '') != 'ACTIVE':
        messages.error(request, "This trip cannot be cancelled as it is not active.")
        return redirect('your_vehicles')
        
    # 1. Penalize the User: Block Cash on Pickup
    if hasattr(rental.user, 'profile'):
        rental.user.profile.cash_on_pickup_blocked = True
        rental.user.profile.save()
        
    # 2. Refund the security deposit (since the trip didn't happen)
    user_wallet = getattr(rental.user, 'wallet', None)
    deposit = getattr(rental, 'security_deposit_held', Decimal('0.00'))
    
    if user_wallet and deposit > 0:
        user_wallet.balance += deposit
        user_wallet.save()
        WalletTransaction.objects.create(
            wallet=user_wallet, amount=deposit, transaction_type='CREDIT',
            description=f'Cancellation Refund (Trip #{rental.id})'
        )
        rental.security_deposit_held = Decimal('0.00')

    # 3. Update the Rental Status
    rental.status = 'CANCELLED'
    closure_notes = "\n\n--- CANCELLED BY HOST ---\nReason: User No-Show / Did not pick up."
    
    if rental.special_notes:
        rental.special_notes += closure_notes
    else:
        rental.special_notes = closure_notes.strip()
        
    rental.save()

    messages.warning(request, f"Trip #{rental.id} cancelled. The user's cash payment privileges have been permanently blocked.")
    return redirect('your_vehicles')