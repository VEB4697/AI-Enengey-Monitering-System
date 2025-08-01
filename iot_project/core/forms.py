from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser # Import your custom user model

class CustomUserCreationForm(UserCreationForm):
    # Add the extra fields you want in the registration form
    first_name = forms.CharField(max_length=30, required=False, help_text='Optional.')
    last_name = forms.CharField(max_length=150, required=False, help_text='Optional.')
    email = forms.EmailField(required=True, help_text='Required. Enter a valid email address.')
    phone_number = forms.CharField(max_length=15, required=False, help_text='Optional. e.g., +919876543210')
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    gender = forms.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_picture = forms.ImageField(required=False)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        # Include all fields you want to be editable on the registration form
        fields = UserCreationForm.Meta.fields + (
            'first_name', 'last_name', 'email', 'phone_number',
            'date_of_birth', 'gender', 'address', 'profile_picture'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make email required if it's not by default in AbstractUser
        self.fields['email'].required = True

    # You might want to override save method if you need custom logic
    # For basic saving, UserCreationForm.save() handles it if fields are in Meta.fields